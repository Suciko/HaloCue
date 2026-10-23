"""Use native document gestures; paragraphs are not separate input widgets."""


def replace_paragraph(page, paragraph, text):
    paragraph.click(click_count=3)
    page.keyboard.insert_text(text)
