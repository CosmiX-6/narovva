"""Curated per-category hashtag pools.

Each pool is ordered roughly by engagement potential on Instagram for tech/news
content. These are the fallback when Google Trends is unavailable and the base
candidates the LLM picks from when it IS available.

Keys match the ContentBrief.category string values produced by poster-core.
"""

from __future__ import annotations

POOLS: dict[str, list[str]] = {
    "ai": [
        "#AI", "#ArtificialIntelligence", "#GenerativeAI", "#MachineLearning",
        "#ChatGPT", "#OpenAI", "#LLM", "#DeepLearning", "#AItools", "#AINews",
        "#AIRevolution", "#AIEthics", "#FutureOfAI", "#DataScience", "#AGI",
        "#Automation", "#NeuralNetwork", "#TechNews", "#Innovation",
    ],
    "technology": [
        "#Tech", "#Technology", "#TechNews", "#Innovation", "#Software",
        "#Startup", "#SiliconValley", "#CyberSecurity", "#CloudComputing",
        "#BigData", "#Gadgets", "#FutureTech", "#Coding", "#TechTrends",
        "#DigitalTransformation", "#IoT", "#Engineering", "#Programming",
    ],
    "science": [
        "#Science", "#Research", "#Discovery", "#STEM", "#Innovation",
        "#SpaceExploration", "#Physics", "#Biology", "#Neuroscience",
        "#ClimateChange", "#Astronomy", "#Genetics", "#Biotech",
        "#ScientificResearch", "#MedicalResearch", "#ScienceNews",
    ],
    "finance": [
        "#Finance", "#Markets", "#StockMarket", "#Investing", "#Economy",
        "#WallStreet", "#FinancialNews", "#Trading", "#Economics",
        "#GlobalEconomy", "#MarketWatch", "#FinTech", "#Crypto",
        "#PersonalFinance", "#Wealth", "#BusinessNews",
    ],
    "business": [
        "#Business", "#BusinessNews", "#Economy", "#Markets", "#Finance",
        "#Entrepreneurship", "#Leadership", "#Startup", "#Innovation",
        "#Corporate", "#Strategy", "#Management", "#GlobalBusiness",
        "#BreakingBusiness", "#Investing",
    ],
    "politics": [
        "#Politics", "#WorldNews", "#GlobalNews", "#Policy", "#Government",
        "#Democracy", "#Geopolitics", "#International", "#CurrentEvents",
        "#BreakingNews", "#Diplomacy", "#PoliticalNews", "#WorldPolitics",
    ],
    "health": [
        "#Health", "#Healthcare", "#Medicine", "#PublicHealth", "#Wellness",
        "#MedicalNews", "#Science", "#Research", "#NHS", "#GlobalHealth",
        "#MentalHealth", "#Innovation", "#Biotech", "#Pharma",
    ],
    "breaking": [
        "#BreakingNews", "#NewsUpdate", "#CurrentEvents", "#WorldNews",
        "#GlobalNews", "#Latest", "#TodayNews", "#News", "#Trending",
        "#Viral", "#MustRead", "#TopStory",
    ],
    "investigation": [
        "#Investigation", "#BreakingNews", "#Journalism", "#Exposé",
        "#NewsAnalysis", "#CurrentEvents", "#TrueStory", "#WorldNews",
        "#DeepDive", "#Accountability",
    ],
    "product_launch": [
        "#ProductLaunch", "#Tech", "#Innovation", "#NewProduct", "#TechNews",
        "#Gadgets", "#Release", "#Startup", "#Design", "#UserExperience",
        "#SiliconValley", "#TechReview",
    ],
    "disaster": [
        "#BreakingNews", "#WorldNews", "#ClimateChange", "#Environment",
        "#GlobalNews", "#Humanitarian", "#Crisis", "#NewsUpdate",
    ],
    "sports": [
        "#Sports", "#SportsNews", "#Athletes", "#Competition", "#Victory",
        "#Championship", "#Game", "#WorldSports",
    ],
    "general": [
        "#News", "#WorldNews", "#BreakingNews", "#CurrentEvents", "#Trending",
        "#TodayNews", "#TopStory", "#NewsUpdate", "#Global", "#MustRead",
    ],
}


def pool_for(category: str) -> list[str]:
    """Return the pool for a brief category, falling back to 'general'."""
    return POOLS.get(str(category).lower(), POOLS["general"])
