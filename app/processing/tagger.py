"""Content tagging: classify stories with descriptive tags.

Tags help users scan the feed quickly:
  📝 long_form   — single-article newsletter or long analysis (>500 words)
  🏢 vendor      — vendor/company announcement, promotional content
  🎙️ podcast     — podcast episode or audio content
  📄 research    — academic paper, arxiv preprint, study
  🚀 launch      — product launch, release announcement
  💰 funding     — fundraising, acquisition, investment news
  🔧 tutorial    — how-to, guide, walkthrough
  📊 benchmark   — benchmark results, comparisons, evaluations
"""

import re

# Tag definitions: (tag_name, display_emoji, patterns_in_title, patterns_in_summary)
TAG_RULES: list[tuple[str, str, list[str], list[str]]] = [
    ("long_form", "📝", [
        # title patterns — these rarely trigger; mostly detected by word count
    ], []),

    ("vendor", "🏢", [
        r"\bannounces?\b", r"\blaunch(?:es|ed|ing)\b.*(?:platform|product|service|tool|api)",
        r"\bintroduc(?:es?|ing)\b", r"\bnow available\b",
        r"\bpowered by\b", r"\bpartner(?:s|ship)\b",
    ], [
        r"\bwe(?:'re| are) (?:excited|thrilled|pleased|happy) to\b",
        r"\bour (?:new|latest|updated)\b",
        r"\btry (?:it|our)\b", r"\bsign up\b", r"\bget started\b",
        r"\bfree trial\b", r"\bpricing\b",
    ]),

    ("podcast", "🎙️", [
        r"\bpodcast\b", r"\bepisode\b", r"\bep\s*\d", r"\bs\d+e\d+\b",
        r"\blisten\b", r"\binterview(?:s|ed)?\b.*with\b",
    ], [
        r"\bpodcast\b", r"\blisten on\b", r"\bspotify\b", r"\byoutube\b.*\bwatch\b",
        r"\baudio\b", r"\brecording\b",
    ]),

    ("research", "📄", [
        r"\barxiv\b", r"\bpaper\b", r"\bpreprint\b",
        r"\bstudy\b.*(?:finds?|shows?|reveals?)\b",
        r":\s*(?:a|an)\b.*\bapproach\b",  # "Title: A Novel Approach to..."
    ], [
        r"\barxiv\.org\b", r"\bpeer.review\b", r"\babstract\b",
        r"\bwe propose\b", r"\bour method\b", r"\bexperiments?\b.*\bshow\b",
        r"\bstate.of.the.art\b", r"\bsota\b", r"\bbenchmark(?:s|ed)?\b.*\bresult",
    ]),

    ("launch", "🚀", [
        r"\breleas(?:es?|ed|ing)\b", r"\blaunch(?:es|ed|ing)\b",
        r"\bnow available\b", r"\bv\d+\.\d+\b",
        r"\bopen.sourc(?:e|es|ed|ing)\b",
        r"\bships?\b",
    ], [
        r"\breleas(?:es?|ed|ing)\b.*\btoday\b",
        r"\bavailable (?:now|today)\b",
        r"\bdownload\b", r"\bgithub\.com\b",
    ]),

    ("funding", "💰", [
        r"\braised?\b.*\$\d", r"\$\d+[mb]\b.*\b(?:round|series|funding)\b",
        r"\bseries [a-e]\b", r"\bfundraising\b",
        r"\bacquir(?:es?|ed|ing)\b", r"\bacquisition\b",
        r"\bvaluation\b", r"\bipo\b", r"\bunicorn\b",
    ], [
        r"\braised?\b.*\$\d", r"\binvestment\b", r"\binvestors?\b",
        r"\bvalued at\b",
    ]),

    ("tutorial", "🔧", [
        r"\bhow to\b", r"\bguide\b", r"\btutorial\b",
        r"\bstep.by.step\b", r"\bwalkthrough\b",
        r"\bbuild(?:ing)?\b.*\bwith\b",
    ], [
        r"\bhow to\b", r"\bstep \d\b", r"\bhere's how\b",
        r"\blet's build\b", r"\byou can\b.*\bby\b",
    ]),

    ("benchmark", "📊", [
        r"\bbenchmark\b", r"\bcompar(?:e|es|ed|ison|ing)\b",
        r"\bvs\.?\b", r"\bevaluat(?:e|es|ed|ion|ing)\b",
        r"\branking\b", r"\bleaderboard\b",
    ], [
        r"\bbenchmark\b", r"\bperformance\b.*\bcompare\b",
        r"\boutperform\b", r"\bbeat(?:s|ing)?\b",
    ]),
]

# Patterns that indicate promo/junk sections (should be filtered, not tagged)
JUNK_PATTERNS: list[str] = [
    r"^subscribe\b", r"^unsubscribe\b",
    r"^a subscription gets you\b",
    r"^become a (?:paying |paid )?subscriber\b",
    r"^(?:manage|update) (?:your )?(?:preferences|subscription)\b",
    r"^(?:share|forward) this\b",
    r"^(?:view|read) (?:in|on) (?:app|browser|web)\b",
    r"^(?:follow|connect with) (?:us|me)\b",
    r"^(?:sponsor(?:ed)?|advertisement)\b",
    r"^(?:brought to you|presented) by\b",
    r"^(?:join|sign up for)\b.*\b(?:community|newsletter|list)\b",
    r"^(?:like|love) this\? (?:share|forward)\b",
    r"^(?:get|try) (?:\w+ )?(?:free|premium|pro)\b",
    r"^(?:powered by|built with)\b",
    r"^invite your friends\b",
    r"^refer(?:ral)?\b.*\b(?:friends?|rewards?|earn)\b",
    r"^earn rewards\b",
    r"^share .* (?:newsletter|email)\b",
]

LONG_FORM_WORD_THRESHOLD = 400


def detect_tags(title: str, summary: str | None = None) -> list[str]:
    """Detect content tags for a story based on title and summary text."""
    tags = []
    title_lower = title.lower()
    summary_lower = (summary or "").lower()
    text = title_lower + " " + summary_lower

    for tag_name, _emoji, title_patterns, summary_patterns in TAG_RULES:
        matched = False
        for pattern in title_patterns:
            if re.search(pattern, title_lower):
                matched = True
                break
        if not matched:
            for pattern in summary_patterns:
                if re.search(pattern, summary_lower):
                    matched = True
                    break
        if matched:
            tags.append(tag_name)

    # Long-form detection by word count
    word_count = len(text.split())
    if word_count > LONG_FORM_WORD_THRESHOLD:
        if "long_form" not in tags:
            tags.append("long_form")

    return tags


def is_junk_section(title: str, summary: str | None = None) -> bool:
    """Check if a segmented 'story' is actually a junk section to filter out.

    Catches: subscribe CTAs, paywall prompts, share buttons, ad sections.
    """
    title_lower = title.lower().strip()

    for pattern in JUNK_PATTERNS:
        if re.search(pattern, title_lower):
            return True

    # Short title + no URL + summary mentions subscribe/paywall
    if summary:
        summary_lower = summary.lower()
        paywall_signals = [
            "become a paying subscriber",
            "unlock the rest",
            "subscriber-only",
            "premium-only",
            "get access to this post",
            "upgrade to paid",
            "subscribe to",
        ]
        if any(s in summary_lower for s in paywall_signals):
            return True

    return False


def get_tag_display(tag: str) -> str:
    """Get the emoji + label for display."""
    tag_display = {
        "long_form": "📝 Long Form",
        "vendor": "🏢 Vendor",
        "podcast": "🎙️ Podcast",
        "research": "📄 Research",
        "launch": "🚀 Launch",
        "funding": "💰 Funding",
        "tutorial": "🔧 Tutorial",
        "benchmark": "📊 Benchmark",
    }
    return tag_display.get(tag, tag)
