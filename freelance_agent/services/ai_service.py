import os
import anthropic

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


PROMPTS = {
    "blog_post": """\
Write a 500-word blog post about the following topic.

Topic: {topic}
Writing style: {style}
Extra details: {details}

Requirements:
- Engaging, SEO-friendly headline (H1)
- Short intro paragraph that hooks the reader
- 3 clearly structured sections with sub-headings
- Actionable conclusion with a call-to-action
- Conversational but authoritative tone
- No filler phrases like "In conclusion" or "In today's world"

Deliver only the finished blog post, no preamble.""",

    "product_desc": """\
Write a high-converting product description for the following product.

Product: {topic}
Tone: {style}
Extra details: {details}

Requirements:
- Punchy headline (under 10 words)
- 3-5 bullet points highlighting key features/benefits
- 2-paragraph body copy focusing on customer outcomes
- Persuasive closing sentence with urgency or social proof

Deliver only the finished product description, no preamble.""",

    "social_pack": """\
Create 5 platform-specific social media posts about the following topic.

Topic: {topic}
Brand voice: {style}
Extra details: {details}

Format exactly like this:
**Twitter/X (max 280 chars):**
[post]

**LinkedIn (professional, 150-300 words):**
[post]

**Instagram (visual focus + hashtags):**
[post]

**Facebook (conversational, 100-200 words):**
[post]

**Twitter/X Thread Opener:**
[post — written as the first tweet of a thread, ending with "🧵 Thread 👇"]

Deliver only the 5 posts, no preamble.""",

    "newsletter": """\
Write a complete email newsletter about the following topic.

Topic: {topic}
Tone: {style}
Extra details: {details}

Format exactly like this:
**Subject Line:** [subject]
**Preview Text:** [90 chars max]

---

[Newsletter body — 300-500 words with 2-3 sections, each with a sub-heading]

---

**CTA Button Text:** [5 words max]

Deliver only the finished newsletter, no preamble.""",
}


def generate_content(order: dict) -> str:
    service_type = order["service_type"]
    template = PROMPTS.get(service_type, PROMPTS["blog_post"])

    prompt = template.format(
        topic=order.get("topic", ""),
        style=order.get("style", "professional"),
        details=order.get("details", "N/A") or "N/A",
    )

    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text
