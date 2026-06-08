"""PC端浏览器自动化服务，使用 agent-browser 控制 Chrome/Chromium。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.utils import utc_iso


class BrowserError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserSession:
    session_id: str
    url: str
    title: str


@dataclass(frozen=True)
class ElementRef:
    ref: str
    tag: str
    text: str | None
    attrs: dict[str, str]
    bounds: dict[str, int] | None = None


@dataclass(frozen=True)
class BrowserLogEntry:
    timestamp: str
    session: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    ok: bool


class PCBrowserService:
    """PC端浏览器自动化服务，封装 agent-browser CLI。"""

    def __init__(self, agent_browser_path: str | None = None) -> None:
        self.agent_browser_path = agent_browser_path or settings.resolved_agent_browser_path
        self._current_session: str | None = None
        self._logs: list[BrowserLogEntry] = []

    def _run(
        self,
        args: list[str],
        timeout: int = 60,
        session: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [self.agent_browser_path]
        if session:
            cmd.extend(["--session", session])
        cmd.extend(args)

        try:
            # Use binary mode to avoid encoding issues on Windows
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_text = ""
            if exc.stdout:
                try:
                    stdout_text = exc.stdout.decode("utf-8", errors="ignore")
                except Exception:
                    pass
            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=124,
                stdout=stdout_text,
                stderr=f"agent-browser command timed out after {timeout}s",
            )
            self._append_log(session=session, command=cmd, result=result)
            raise BrowserError(result.stderr)

        # Decode output with UTF-8, fallback to ignore errors
        stdout_text = ""
        stderr_text = ""
        if result.stdout:
            try:
                stdout_text = result.stdout.decode("utf-8")
            except UnicodeDecodeError:
                stdout_text = result.stdout.decode("utf-8", errors="ignore")
        if result.stderr:
            try:
                stderr_text = result.stderr.decode("utf-8")
            except UnicodeDecodeError:
                stderr_text = result.stderr.decode("utf-8", errors="ignore")

        decoded_result = subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )

        self._append_log(session=session, command=cmd, result=decoded_result)
        if decoded_result.returncode != 0:
            raise BrowserError(decoded_result.stderr.strip() or "agent-browser command failed")

        return decoded_result

    def _append_log(self, *, session: str | None, command: list[str], result: subprocess.CompletedProcess[str]) -> None:
        self._logs.append(
            BrowserLogEntry(
                timestamp=utc_iso(),
                session=session or self._current_session or "default",
                command=command,
                returncode=result.returncode,
                stdout=(result.stdout or "")[-4000:],
                stderr=(result.stderr or "")[-4000:],
                ok=result.returncode == 0,
            )
        )
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]

    def logs(self, session: str | None = None, limit: int = 100) -> list[BrowserLogEntry]:
        entries = self._logs
        if session:
            entries = [entry for entry in entries if entry.session == session]
        return entries[-max(1, min(limit, 500)) :]

    def open(
        self,
        url: str,
        session: str | None = None,
        headed: bool = False,
    ) -> BrowserSession:
        """打开浏览器并导航到指定URL。"""
        args = ["open", url]
        if headed:
            args.insert(0, "--headed")

        result = self._run(args, session=session)
        self._current_session = session or "default"

        lines = result.stdout.strip().split("\n")
        title = ""
        final_url = url
        for line in lines:
            if line.startswith("✓"):
                title = line[1:].strip()
            elif line.strip().startswith("http"):
                final_url = line.strip()

        return BrowserSession(
            session_id=self._current_session,
            url=final_url,
            title=title,
        )

    def close(self, session: str | None = None) -> None:
        """关闭浏览器会话。"""
        self._run(["close"], session=session)
        if session is None or session == self._current_session:
            self._current_session = None

    def close_all(self) -> None:
        """关闭所有浏览器会话。"""
        self._run(["close", "--all"])
        self._current_session = None

    def snapshot(
        self,
        interactive_only: bool = True,
        session: str | None = None,
        include_bounds: bool = False,
    ) -> list[ElementRef]:
        """获取页面快照，返回元素引用列表。"""
        args = ["snapshot", "--json"]
        if interactive_only:
            args.append("-i")

        result = self._run(args, session=session)
        elements: list[ElementRef] = []
        refs_data: dict[str, dict] = {}
        snapshot_text = ""

        try:
            parsed = json.loads(result.stdout.strip())
            refs_data = parsed.get("data", {}).get("refs", {})
            snapshot_text = parsed.get("data", {}).get("snapshot", "")
        except (json.JSONDecodeError, TypeError):
            # Fallback to parsing plain text output
            snapshot_text = result.stdout.strip()

        for line in snapshot_text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("Page:") or line.startswith("URL:"):
                continue

            ref = self._parse_snapshot_line(line)
            if ref:
                # Add bounds if available from refs_data
                bounds = None
                ref_key = ref.ref[1:] if ref.ref.startswith("@") else ref.ref  # Remove @ prefix
                ref_info = refs_data.get(ref_key) or refs_data.get(ref.ref)
                if ref_info and "bounds" in ref_info:
                    bounds = ref_info["bounds"]
                elements.append(ElementRef(
                    ref=ref.ref,
                    tag=ref.tag,
                    text=ref.text,
                    attrs=ref.attrs,
                    bounds=bounds,
                ))

        # If include_bounds, fetch bounds via JavaScript
        if include_bounds and elements:
            elements = self._fetch_element_bounds(elements, session=session)

        return elements

    def _fetch_element_bounds(
        self,
        elements: list[ElementRef],
        session: str | None = None,
    ) -> list[ElementRef]:
        """Fetch bounding boxes for elements via agent-browser get box command."""
        result_elements = []

        for e in elements:
            bounds = None
            try:
                # Use agent-browser get box command to get element bounds
                box_result = self._run(["get", "box", e.ref], session=session, timeout=5)
                # Parse output like:
                # x:      0
                # y:      0
                # width:  929
                # height: 861
                import re
                lines = box_result.stdout.strip().split("\n")
                values = {}
                for line in lines:
                    match = re.match(r"(\w+):\s*(\d+)", line.strip())
                    if match:
                        values[match.group(1)] = int(match.group(2))

                if "x" in values and "y" in values and "width" in values and "height" in values:
                    x, y, w, h = values["x"], values["y"], values["width"], values["height"]
                    bounds = {
                        "left": x,
                        "top": y,
                        "right": x + w,
                        "bottom": y + h,
                        "width": w,
                        "height": h,
                    }
            except Exception:
                pass

            result_elements.append(ElementRef(
                ref=e.ref,
                tag=e.tag,
                text=e.text,
                attrs=e.attrs,
                bounds=bounds,
            ))

        return result_elements

    def _parse_snapshot_line(self, line: str) -> ElementRef | None:
        """解析快照行，提取元素引用。"""
        import re

        # Try format from JSON output: "- heading \"Example Domain\" [level=1, ref=e1]"
        match = re.match(r"^-\s+(\w+)\s+(?:\"([^\"]*)\"\s+)?\[.*ref=(@?e\d+).*\]$", line)
        if match:
            tag = match.group(1)
            text = match.group(2)
            ref = match.group(3)
            if not ref.startswith("@"):
                ref = "@" + ref

            attrs: dict[str, str] = {}
            attr_pattern = r'(\w+)=([^\],]+)'
            for attr_match in re.finditer(attr_pattern, line):
                attrs[attr_match.group(1)] = attr_match.group(2).strip('"')
            return ElementRef(ref=ref, tag=tag, text=text, attrs=attrs)

        # Try format from plain text output: "@e1 [tag] \"text\""
        match = re.match(r"^(@e\d+)\s+\[([^\]]+)\](?:\s+\"([^\"]*)\")?", line)
        if not match:
            return None

        ref = match.group(1)
        tag = match.group(2)
        text = match.group(3)

        attrs: dict[str, str] = {}
        attr_pattern = r'(\w+)="([^"]*)"'
        for attr_match in re.finditer(attr_pattern, line):
            attrs[attr_match.group(1)] = attr_match.group(2)

        return ElementRef(ref=ref, tag=tag, text=text, attrs=attrs)

    def click(
        self,
        element_ref: str,
        session: str | None = None,
        new_tab: bool = False,
    ) -> None:
        """点击元素。"""
        args = ["click", element_ref]
        if new_tab:
            args.append("--new-tab")
        self._run(args, session=session)

    def fill(
        self,
        element_ref: str,
        text: str,
        session: str | None = None,
    ) -> None:
        """填充输入框（先清空再输入）。"""
        self._run(["fill", element_ref, text], session=session)

    def type_text(
        self,
        element_ref: str,
        text: str,
        session: str | None = None,
    ) -> None:
        """在元素中输入文本（不清空）。"""
        self._run(["type", element_ref, text], session=session)

    def press(self, key: str, session: str | None = None) -> None:
        """按键。"""
        self._run(["press", key], session=session)

    def hover(self, element_ref: str, session: str | None = None) -> None:
        """悬停在元素上。"""
        self._run(["hover", element_ref], session=session)

    def scroll(
        self,
        direction: str,
        amount: int = 300,
        session: str | None = None,
    ) -> None:
        """滚动页面。direction: up/down/left/right"""
        self._run(["scroll", direction, str(amount)], session=session)

    def screenshot(
        self,
        path: str | Path,
        full_page: bool = False,
        session: str | None = None,
    ) -> Path:
        """截取屏幕截图。"""
        args = ["screenshot", str(path)]
        if full_page:
            args.append("--full")
        self._run(args, session=session)
        return Path(path)

    def get_text(self, element_ref: str, session: str | None = None) -> str:
        """获取元素的文本内容。"""
        result = self._run(["get", "text", element_ref], session=session)
        return result.stdout.strip()

    def get_url(self, session: str | None = None) -> str:
        """获取当前页面URL。"""
        result = self._run(["get", "url"], session=session)
        return result.stdout.strip()

    def get_title(self, session: str | None = None) -> str:
        """获取当前页面标题。"""
        result = self._run(["get", "title"], session=session)
        return result.stdout.strip()

    def wait_for_element(
        self,
        element_ref: str,
        timeout_ms: int = 25000,
        session: str | None = None,
    ) -> None:
        """等待元素出现。"""
        self._run(["wait", element_ref, "--timeout", str(timeout_ms)], session=session)

    def wait_for_text(
        self,
        text: str,
        timeout_ms: int = 25000,
        session: str | None = None,
    ) -> None:
        """等待文本出现。"""
        self._run(
            ["wait", "--text", text, "--timeout", str(timeout_ms)],
            session=session,
        )

    def wait_for_url(
        self,
        pattern: str,
        timeout_ms: int = 25000,
        session: str | None = None,
    ) -> None:
        """等待URL匹配模式。"""
        self._run(
            ["wait", "--url", pattern, "--timeout", str(timeout_ms)],
            session=session,
        )

    def wait_for_load(
        self,
        load_type: str = "networkidle",
        session: str | None = None,
    ) -> None:
        """等待页面加载完成。load_type: networkidle/domcontentloaded"""
        self._run(["wait", "--load", load_type], session=session)

    def eval_js(
        self,
        script: str,
        session: str | None = None,
    ) -> str:
        """执行JavaScript并返回结果。"""
        result = self._run(["eval", script], session=session)
        return result.stdout.strip()

    def select_option(
        self,
        element_ref: str,
        value: str,
        session: str | None = None,
    ) -> None:
        """选择下拉框选项。"""
        self._run(["select", element_ref, value], session=session)

    def check(self, element_ref: str, session: str | None = None) -> None:
        """勾选复选框。"""
        self._run(["check", element_ref], session=session)

    def uncheck(self, element_ref: str, session: str | None = None) -> None:
        """取消勾选复选框。"""
        self._run(["uncheck", element_ref], session=session)

    def upload_file(
        self,
        element_ref: str,
        file_path: str | Path,
        session: str | None = None,
    ) -> None:
        """上传文件。"""
        self._run(["upload", element_ref, str(file_path)], session=session)

    def save_state(
        self,
        path: str | Path,
        session: str | None = None,
    ) -> None:
        """保存会话状态（cookies、localStorage等）。"""
        self._run(["state", "save", str(path)], session=session)

    def load_state(
        self,
        path: str | Path,
        session: str | None = None,
    ) -> None:
        """加载会话状态。"""
        self._run(["state", "load", str(path)], session=session)

    def tab_list(self, session: str | None = None) -> list[dict[str, str]]:
        """列出所有标签页。"""
        result = self._run(["tab"], session=session)
        tabs: list[dict[str, str]] = []

        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and line.startswith("t"):
                parts = line.split(maxsplit=1)
                if len(parts) >= 1:
                    tabs.append({"tab_id": parts[0], "title": parts[1] if len(parts) > 1 else ""})

        return tabs

    def tab_new(
        self,
        url: str | None = None,
        label: str | None = None,
        session: str | None = None,
    ) -> None:
        """打开新标签页。"""
        args = ["tab", "new"]
        if label:
            args.extend(["--label", label])
        if url:
            args.append(url)
        self._run(args, session=session)

    def tab_switch(
        self,
        tab_id_or_label: str,
        session: str | None = None,
    ) -> None:
        """切换到指定标签页。"""
        self._run(["tab", tab_id_or_label], session=session)

    def tab_switch_url(self, pattern: str, session: str | None = None) -> None:
        """按 URL 模式切换到指定标签页或 webview。"""
        self._run(["tab", "--url", pattern], session=session)

    def tab_close(
        self,
        tab_id_or_label: str | None = None,
        session: str | None = None,
    ) -> None:
        """关闭标签页。"""
        args = ["tab", "close"]
        if tab_id_or_label:
            args.append(tab_id_or_label)
        self._run(args, session=session)

    def record_start(
        self,
        output_path: str | Path,
        session: str | None = None,
    ) -> None:
        """开始录制视频。"""
        self._run(["record", "start", str(output_path)], session=session)

    def record_stop(self, session: str | None = None) -> None:
        """停止录制视频。"""
        self._run(["record", "stop"], session=session)

    def find_and_click(
        self,
        text: str,
        exact: bool = False,
        session: str | None = None,
    ) -> None:
        """通过文本查找并点击元素。"""
        args = ["find", "text", text, "click"]
        if exact:
            args.append("--exact")
        self._run(args, session=session)

    def find_and_fill(
        self,
        label: str,
        text: str,
        session: str | None = None,
    ) -> None:
        """通过标签查找输入框并填充。"""
        self._run(["find", "label", label, "fill", text], session=session)
