from io import BytesIO

from PIL import Image


def png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_template_match_returns_center_of_best_match() -> None:
    from app.services.visual_action_service import VisualActionService

    screen = Image.new("RGB", (24, 24), "white")
    for x in range(8, 14):
        for y in range(10, 16):
            screen.putpixel((x, y), (20, 120, 240))
    template = screen.crop((8, 10, 14, 16))

    match = VisualActionService().find_template(
        screen_png=png_bytes(screen),
        template_png=png_bytes(template),
        threshold=0.99,
    )

    assert match.found is True
    assert match.x == 11
    assert match.y == 13
    assert match.score == 1.0


def test_template_match_reports_not_found_below_threshold() -> None:
    from app.services.visual_action_service import VisualActionService

    screen = Image.new("RGB", (16, 16), "white")
    template = Image.new("RGB", (4, 4), "black")

    match = VisualActionService().find_template(
        screen_png=png_bytes(screen),
        template_png=png_bytes(template),
        threshold=0.99,
    )

    assert match.found is False
