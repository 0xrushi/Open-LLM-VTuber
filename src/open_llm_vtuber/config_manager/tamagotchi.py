from typing import ClassVar, Dict

from pydantic import BaseModel, Field

from .i18n import Description, I18nMixin


class TamagotchiConfig(I18nMixin, BaseModel):
    """Configuration for the desktop pet (tamagotchi) mode."""

    enabled: bool = Field(default=False, alias="enabled")
    window_width: int = Field(default=400, alias="window_width")
    window_height: int = Field(default=600, alias="window_height")
    always_on_top: bool = Field(default=True, alias="always_on_top")
    click_through: bool = Field(default=True, alias="click_through")
    opacity: float = Field(default=1.0, alias="opacity")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "enabled": Description(
            en="Enable the desktop pet (tamagotchi) mode",
            zh="启用桌面宠物（拓麻歌子）模式",
        ),
        "window_width": Description(
            en="Window width in pixels",
            zh="窗口宽度（像素）",
        ),
        "window_height": Description(
            en="Window height in pixels",
            zh="窗口高度（像素）",
        ),
        "always_on_top": Description(
            en="Keep the window always on top of other windows",
            zh="保持窗口始终置顶",
        ),
        "click_through": Description(
            en="Allow mouse clicks to pass through transparent areas",
            zh="允许鼠标点击穿透透明区域",
        ),
        "opacity": Description(
            en="Window opacity (0.0 to 1.0)",
            zh="窗口透明度（0.0 到 1.0）",
        ),
    }
