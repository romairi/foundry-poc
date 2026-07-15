import json
import re

# Simulated corporate knowledge base
_KNOWLEDGE_BASE = [
    {"title": "Shuttle Route 101", "content": "Route 101: Mon-Fri, 8:00, 9:00, 12:00, 17:00, 18:00. Main Office → Tech Park."},
    {"title": "Remote Work Policy", "content": "Remote work allowed up to 3 days/week with manager approval."},
    {"title": "IT Help Desk Contact", "content": "IT Support: ext 5555, helpdesk@company.com, hours 8:00-20:00."},
    {"title": "Expense Reporting & Reimbursement", "content": "Submit expense reports within 30 days. Receipts required for items over $25."},
]

# Structural words to filter out so they don't skew search match results
STOP_WORDS = {
    "what", "whats", "what's", "how", "why", "who", "where", "when", "the", "is", "are", 
    "a", "an", "on", "in", "at", "to", "for", "with", "about", "and", "or", "of", "do", 
    "does", "did", "you", "me", "i", "my", "our", "find", "search", "get", "show", "tell"
}


def search_corporate(query: str) -> str:
    """
    Search corporate knowledge base for policies, schedules, contacts.

    :param query: Search query in natural language.
    :return: Ranked search results as JSON string.
    """
    # Normalize input: lowercase and strip out punctuation
    clean_query = re.sub(r"[^\w\s]", "", query.lower())
    query_words = [word for word in clean_query.split() if word and word not in STOP_WORDS]

    # If the user only sent stop words, fall back to the raw cleaned words
    if not query_words:
        query_words = [word for word in clean_query.split() if word]

    scored_results = []
    for item in _KNOWLEDGE_BASE:
        score = 0
        title_lower = item["title"].lower()
        content_lower = item["content"].lower()

        for word in query_words:
            # Weighted matching: Title hits are high signal (5 pts), content hits are standard (2 pts)
            if word in title_lower:
                score += 5
            if word in content_lower:
                score += 2

        if score > 0:
            scored_results.append((score, item))

    # Rank results by matching score (highest first)
    scored_results.sort(key=lambda x: x[0], reverse=True)
    ranked_results = [item for _, item in scored_results]

    return json.dumps({
        "query": query,
        "keywords_extracted": query_words,
        "found": len(ranked_results),
        "results": ranked_results[:3]
    }, ensure_ascii=False)