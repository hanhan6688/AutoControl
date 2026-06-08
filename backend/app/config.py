import os
import shutil
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


SOURCE_BACKEND_DIR = Path(__file__).resolve().parents[1]
SOURCE_PROJECT_ROOT = SOURCE_BACKEND_DIR.parent


def _runtime_root() -> Path:
    configured_root = os.environ.get("MOBILE_AI_TESTOPS_RUNTIME_ROOT")
    if configured_root:
        return Path(configured_root).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SOURCE_PROJECT_ROOT


def _backend_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _runtime_root() / "backend"
    return SOURCE_BACKEND_DIR


class Settings(BaseSettings):
    app_name: str = "Mobile AI TestOps"
    database_url: str = "sqlite:///./mobile_ai_testops.db"
    python_path: str = ""
    adb_path: str = ""
    ios_path: str = ""
    hdc_path: str = ""
    scrcpy_path: str = ""
    ffmpeg_path: str = ""
    maestro_path: str = ""
    agent_browser_path: str = ""
    adb_keyboard_apk_path: str = ""
    autoglm_base_url: str = "http://localhost:8000/v1"
    autoglm_model: str = "autoglm-phone-9b"
    autoglm_api_key: str = "EMPTY"
    autoglm_max_steps: int = 100
    autoglm_lang: str = "cn"
    autoglm_wda_url: str = "http://localhost:8100"
    u2_enabled: bool = True
    u2_port_start: int = 7912
    wda_enabled: bool = True
    pc_agent_enabled: bool = True
    pc_agent_provider: str = "minimax_auto"
    pc_agent_base_url: str = "https://api.minimaxi.com/v1"
    pc_agent_model: str = "MiniMax-M2.7"
    pc_agent_api_key: str = ""
    pc_agent_timeout_seconds: float = 30.0
    pc_agent_temperature: float = 0.1
    pc_agent_max_tokens: int = 300
    result_assertion_enabled: bool = True
    result_assertion_base_url: str = ""
    result_assertion_model: str = ""
    result_assertion_api_key: str = ""
    result_assertion_timeout_seconds: float = 20.0
    # Requirement analysis AI (DeepSeek for test case generation)
    deepseek_req_enabled: bool = True
    deepseek_req_base_url: str = "https://api.deepseek.com"
    deepseek_req_model: str = "deepseek-chat"
    deepseek_req_api_key: str = ""
    deepseek_req_timeout_seconds: float = 120.0
    deepseek_req_temperature: float = 0.3
    deepseek_req_max_tokens: int = 4000
    screenshot_timeout_seconds: float = 20.0
    automation_target_app_name: str = ""
    ocr_base_url: str = ""
    android_stream_provider: str = "scrcpy-h264"
    minicap_port_start: int = 1717
    scrcpy_web_port_start: int = 28183
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ]
    cors_origin_regex: str = r"http://(localhost|127\.0\.0\.1|172\.\d+\.\d+\.\d+):\d+"
    api_test_default_timeout: float = 30.0

    model_config = SettingsConfigDict(
        env_file=str(_backend_dir() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def backend_dir(self) -> Path:
        return _backend_dir()

    @property
    def project_root(self) -> Path:
        return self.backend_dir.parent

    @property
    def runtime_root(self) -> Path:
        return _runtime_root()

    @property
    def env_file_path(self) -> Path:
        return self.backend_dir / ".env"

    @property
    def resolved_database_url(self) -> str:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url

        raw_path = self.database_url[len(prefix):]
        if raw_path == ":memory:":
            return self.database_url

        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = self.backend_dir / db_path
        return f"{prefix}{db_path.as_posix()}"

    @property
    def static_dir(self) -> Path:
        return self.backend_dir / "static"

    @property
    def uploads_dir(self) -> Path:
        return self.static_dir / "uploads"

    @property
    def scripts_dir(self) -> Path:
        return self.backend_dir / "scripts"

    @property
    def tools_dir(self) -> Path:
        return self.runtime_root / "tools"

    @property
    def open_autoglm_root(self) -> Path:
        return self.tools_dir / "Open-AutoGLM"

    @property
    def minicap_dir(self) -> Path:
        return self.tools_dir / "minicap"

    @property
    def venv_dir(self) -> Path | None:
        """Return the virtual environment directory if configured."""
        if not self.python_path:
            return None
        venv_path = Path(self.python_path)
        if venv_path.is_absolute():
            return venv_path if venv_path.exists() else None
        relative_path = self.runtime_root / self.python_path
        return relative_path if relative_path.exists() else None

    @property
    def resolved_python_path(self) -> str:
        """Return the Python executable path, preferring venv if configured."""
        if self.venv_dir:
            python_exe = self.venv_dir / "Scripts" / "python.exe"
            if python_exe.exists():
                return str(python_exe)
        return sys.executable

    @property
    def scrcpy_server_path(self) -> Path:
        return self.tools_dir / "scrcpy-win64" / "scrcpy-server"

    @property
    def resolved_adb_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.adb_path,
            bundled_candidates=[
                self.tools_dir / "scrcpy-win64" / "adb.exe",
                self.tools_dir / "platform-tools" / "adb.exe",
            ],
            path_name="adb",
        )

    @property
    def resolved_scrcpy_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.scrcpy_path,
            bundled_candidates=[self.tools_dir / "scrcpy-win64" / "scrcpy.exe"],
            path_name="scrcpy",
        )

    @property
    def resolved_ffmpeg_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.ffmpeg_path,
            bundled_candidates=[
                self.tools_dir / "ffmpeg" / "bin" / "ffmpeg.exe",
                self.tools_dir / "ffmpeg.exe",
            ],
            path_name="ffmpeg",
        )

    @property
    def resolved_ios_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.ios_path,
            bundled_candidates=[self.tools_dir / "go-ios" / "ios.exe"],
            path_name="ios",
        )

    @property
    def resolved_hdc_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.hdc_path,
            bundled_candidates=[
                self.tools_dir / "hdc" / "hdc.exe",
                self.tools_dir / "command-line-tools" / "bin" / "hdc.exe",
                self.tools_dir / "openharmony" / "hdc.exe",
            ],
            path_name="hdc",
        )

    @property
    def resolved_maestro_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.maestro_path,
            bundled_candidates=[
                self.tools_dir / "maestro" / "bin" / "maestro.bat",
                self.tools_dir / "maestro" / "maestro.bat",
                self.tools_dir / "maestro" / "maestro.exe",
            ],
            path_name="maestro",
        )

    @property
    def resolved_agent_browser_path(self) -> str:
        return self._resolve_executable(
            configured_path=self.agent_browser_path,
            bundled_candidates=[
                self.tools_dir / "agent-browser" / "node_modules" / ".bin" / "agent-browser.cmd",
                self.tools_dir / "agent-browser" / "node_modules" / ".bin" / "agent-browser",
                Path(r"D:\_software\nvm\node_global\agent-browser.cmd"),
            ],
            path_name="agent-browser",
        )

    @property
    def resolved_adb_keyboard_apk_path(self) -> Path | None:
        if not self.adb_keyboard_apk_path:
            return None
        candidate = Path(self.adb_keyboard_apk_path)
        if candidate.is_absolute():
            return candidate if candidate.exists() else None
        relative_candidate = self.runtime_root / self.adb_keyboard_apk_path
        return relative_candidate if relative_candidate.exists() else None

    def _resolve_executable(
        self,
        configured_path: str,
        bundled_candidates: list[Path],
        path_name: str,
    ) -> str:
        if configured_path:
            candidate = Path(configured_path)
            if candidate.is_absolute() and candidate.exists():
                return str(candidate)
            relative_candidate = self.runtime_root / configured_path
            if relative_candidate.exists():
                return str(relative_candidate)
            which_result = shutil.which(configured_path)
            if which_result:
                return which_result

        for candidate in bundled_candidates:
            if candidate.exists():
                return str(candidate)

        which_result = shutil.which(path_name)
        return which_result or path_name


settings = Settings()
