from datetime import date

from agent_trending.articles import (
    BlogDefinition,
    parse_article_page,
    parse_blog_index,
)


def test_openai_index_parses_yearless_official_blog_date():
    html = """
    <article><a href="/blog/agent-harness"><h3>Building agent harnesses</h3>
    <p>Aug 25</p></a></article>
    """

    results = parse_blog_index(
        html,
        blog=BlogDefinition(
            "OpenAI", "https://developers.openai.com/blog/", "/blog/"
        ),
        reference_date=date(2026, 8, 30),
    )

    assert results == [
        (
            "Building agent harnesses",
            "https://developers.openai.com/blog/agent-harness",
            date(2026, 8, 25),
        )
    ]


def test_anthropic_index_rejects_external_and_non_engineering_links():
    html = """
    <article><a href="/engineering/managed-agents"><h3>Managed agents</h3>
    <p>Aug 24, 2026</p></a></article>
    <article><a href="/news/product"><h3>Product news</h3><p>Aug 25, 2026</p></a></article>
    <article><a href="https://example.com/engineering/post"><h3>External</h3>
    <p>Aug 26, 2026</p></a></article>
    """

    results = parse_blog_index(
        html,
        blog=BlogDefinition(
            "Anthropic", "https://www.anthropic.com/engineering", "/engineering/"
        ),
        reference_date=date(2026, 8, 30),
    )

    assert [item[1] for item in results] == [
        "https://www.anthropic.com/engineering/managed-agents"
    ]


def test_article_page_uses_official_metadata_and_readable_content():
    html = """
    <html><head><meta property="og:title" content="Agent systems">
    <meta property="article:published_time" content="2026-08-25T10:00:00Z"></head>
    <body><main><nav>skip</nav><h1>Agent systems</h1><p>Useful article body.</p>
    <script>ignore()</script></main></body></html>
    """

    title, published, content = parse_article_page(
        html, fallback_title="Fallback", fallback_date=date(2026, 8, 24)
    )

    assert title == "Agent systems"
    assert published == date(2026, 8, 25)
    assert content == "Agent systems Useful article body."
