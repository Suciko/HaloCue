"""Synthetic Agent responses shared by onboarding automation and local UI checks."""

from halocue_writing.providers import FakeWritingProvider


def assert_readable_surface(page, selector, text_selector="p"):
    colors = page.wait_for_function(
        """({selector, textSelector}) => {
      const surface = document.querySelector(selector), text = surface?.querySelector(textSelector);
      if (!surface?.isConnected || !text) return false;
      const background = getComputedStyle(surface).backgroundColor;
      const foreground = getComputedStyle(text).color;
      return background && foreground ? {background, foreground} : false;
    }""",
        arg={"selector": selector, "textSelector": text_selector},
    ).json_value()

    def luminance(color):
        rgb = [
            float(item) / 255 for item in color.removeprefix("rgb(").removesuffix(")").split(",")
        ]
        linear = [
            item / 12.92 if item <= 0.04045 else ((item + 0.055) / 1.055) ** 2.4 for item in rgb
        ]
        return sum(item * weight for item, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    foreground, background = luminance(colors["foreground"]), luminance(colors["background"])
    assert (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05) >= 4.5, (
        colors
    )


class DraftingProvider(FakeWritingProvider):
    def discuss_work(self, messages, context):
        if context.get("task_contract", {}).get("id") == "scene.draft.generate":
            return {
                "text": "按本场要求准备了正文候选，请在原位核对。",
                "questions": [],
                "tool_calls": [
                    {
                        "tool": "propose_scene_draft",
                        "arguments": {
                            "text": "旁白: 深夜，活动室的提示灯亮了一次。\n旁白: 她们停下核对记录，等待下一次回应。",
                            "reason": "按作者明确要求起草本场。",
                        },
                    }
                ],
            }
        return super().discuss_work(messages, context)
