"""HTML → PDF(WeasyPrint,M5-0 基础;M5-1 课表导出建立于此)。

WeasyPrint 的系统依赖(Pango/Cairo)与中文内嵌字型只装在 **worker** 映像;
导出一律走背景任务。故 `weasyprint` 为延迟导入——api 导入本模组不会失败,
只有真正呼叫 `render_pdf`(在 worker)才需要那些依赖。
"""


def render_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """把 HTML 字串渲染成 PDF bytes。中文由映像内嵌的 Noto CJK 字型呈现。"""
    from weasyprint import HTML  # 延迟导入:见模组说明

    return HTML(string=html, base_url=base_url).write_pdf()
