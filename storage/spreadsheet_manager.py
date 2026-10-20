"""
Finance Shorts - Excel Spreadsheet Manager
Handles reading and writing the finance_content_queue.xlsx workbook.
SQLite is authoritative for job state; Excel is the human-editable topic queue
and status dashboard.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side
)
from openpyxl.utils import get_column_letter

import config

logger = logging.getLogger(__name__)

# ── Column Definitions ────────────────────────────────────────────────────────

CONTENT_COLUMNS = [
    "topic_id",
    "topic",
    "category",
    "difficulty_level",
    "audience",
    "key_learning_objective",
    "prerequisites",
    "research_sources",
    "research_summary",
    "script",
    "video_title",
    "video_description",
    "keywords",
    "estimated_duration",
    "narration_file",
    "captions_file",
    "video_file",
    "scheduled_at",
    "status",
    "youtube_video_id",
    "instagram_media_id",
    "published_url_youtube",
    "published_url_instagram",
    "retry_count",
    "last_error",
    "created_at",
    "updated_at",
]

SETTINGS_COLUMNS = ["setting_key", "setting_value", "description"]

# ── Styles ────────────────────────────────────────────────────────────────────

_HEADER_FILL   = PatternFill("solid", fgColor="1A1A2E")
_HEADER_FONT   = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_HEADER_ALIGN  = Alignment(horizontal="center", vertical="center", wrap_text=True)
_THIN_SIDE     = Side(style="thin", color="CCCCCC")
_THIN_BORDER   = Border(
    left=_THIN_SIDE, right=_THIN_SIDE,
    top=_THIN_SIDE, bottom=_THIN_SIDE
)
_STATUS_COLORS = {
    "IDEA":             "F0F4FF",
    "READY":            "E8F5E9",
    "RESEARCHING":      "FFF9C4",
    "RESEARCHED":       "F3E5F5",
    "SCRIPT_GENERATED": "E3F2FD",
    "NEEDS_REVIEW":     "FFF3E0",
    "SCRIPT_APPROVED":  "E8F5E9",
    "PRODUCING":        "FFF9C4",
    "VIDEO_READY":      "E0F7FA",
    "SCHEDULED":        "F3E5F5",
    "UPLOADING":        "FFF9C4",
    "PUBLISHED":        "E8F5E9",
    "FAILED":           "FFEBEE",
}


# ── Topic Seed Data (100 carefully sequenced topics) ─────────────────────────

def _build_topic_seed() -> list[dict[str, Any]]:
    """
    Returns 100 carefully sequenced finance topics from beginner to advanced.
    topic_id format: FIN001 – FIN100
    difficulty_level: 1=Beginner, 2=Elementary, 3=Intermediate, 4=Advanced, 5=Expert
    """
    topics = [
        # ── Level 1: Money Fundamentals (FIN001–FIN020) ───────────────────
        {
            "topic_id": "FIN001",
            "topic": "What Is Money? The Origin and Purpose of Currency",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Understand what money is, why it was invented, and how it replaced barter",
            "prerequisites": "",
        },
        {
            "topic_id": "FIN002",
            "topic": "Income vs Expenses: The Foundation of Personal Finance",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Distinguish income from expenses and understand why the gap between them matters",
            "prerequisites": "FIN001",
        },
        {
            "topic_id": "FIN003",
            "topic": "Assets vs Liabilities: What Rich People Know",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Define assets and liabilities and explain why building assets is the path to wealth",
            "prerequisites": "FIN002",
        },
        {
            "topic_id": "FIN004",
            "topic": "What Is Inflation? Why Your Money Loses Value Over Time",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Explain inflation with Indian examples and why keeping cash idle is risky",
            "prerequisites": "FIN001",
        },
        {
            "topic_id": "FIN005",
            "topic": "Simple Interest Explained with Easy Examples",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Calculate simple interest using P×R×T/100 with relatable INR examples",
            "prerequisites": "FIN001",
        },
        {
            "topic_id": "FIN006",
            "topic": "Compound Interest: The 8th Wonder of the World",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Show how compound interest grows wealth exponentially using a ₹10,000 example",
            "prerequisites": "FIN005",
        },
        {
            "topic_id": "FIN007",
            "topic": "Saving vs Investing: What Is the Difference?",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Clarify the difference between saving (safety) and investing (growth) and when to do each",
            "prerequisites": "FIN003",
        },
        {
            "topic_id": "FIN008",
            "topic": "The 50-30-20 Budgeting Rule Explained Simply",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Apply the 50/30/20 rule to a ₹30,000 monthly salary with real budget categories",
            "prerequisites": "FIN002",
        },
        {
            "topic_id": "FIN009",
            "topic": "Purchasing Power: How Inflation Erodes Your Rupee",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Show with numbers how ₹1,000 today buys less than ₹1,000 ten years ago",
            "prerequisites": "FIN004",
        },
        {
            "topic_id": "FIN010",
            "topic": "Why You Need an Emergency Fund (And How Big It Should Be)",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Explain the 3–6 month expense rule for emergency funds using Indian scenarios",
            "prerequisites": "FIN002",
        },
        {
            "topic_id": "FIN011",
            "topic": "The Rule of 72: How Long to Double Your Money",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Use the Rule of 72 to estimate doubling time at common Indian interest rates",
            "prerequisites": "FIN006",
        },
        {
            "topic_id": "FIN012",
            "topic": "Net Worth: What It Is and How to Calculate Yours",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Calculate net worth (Assets − Liabilities) with a simple Indian household example",
            "prerequisites": "FIN003",
        },
        {
            "topic_id": "FIN013",
            "topic": "Fixed vs Variable Expenses: Know Where Your Money Goes",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Categorise monthly expenses into fixed and variable to find savings opportunities",
            "prerequisites": "FIN002",
        },
        {
            "topic_id": "FIN014",
            "topic": "The Time Value of Money: ₹1,000 Today vs Tomorrow",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Explain why money received today is worth more than the same amount received later",
            "prerequisites": "FIN006",
        },
        {
            "topic_id": "FIN015",
            "topic": "Needs vs Wants: The First Step to Financial Control",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Distinguish needs from wants and show how this distinction changes spending habits",
            "prerequisites": "FIN002",
        },
        {
            "topic_id": "FIN016",
            "topic": "How Banks Make Money: The Business of Borrowing and Lending",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Explain the spread model: how banks profit from the difference between deposit and loan rates",
            "prerequisites": "FIN005",
        },
        {
            "topic_id": "FIN017",
            "topic": "Good Debt vs Bad Debt: Not All Debt Is Equal",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Distinguish productive debt (education, business) from destructive debt (EMIs on deprecating goods)",
            "prerequisites": "FIN003",
        },
        {
            "topic_id": "FIN018",
            "topic": "Financial Goals: Short, Medium, and Long Term",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Set SMART financial goals across three time horizons with Indian examples",
            "prerequisites": "FIN007",
        },
        {
            "topic_id": "FIN019",
            "topic": "Opportunity Cost: Every Financial Decision Has a Price",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Define opportunity cost and apply it to everyday money decisions like buying vs investing",
            "prerequisites": "FIN007",
        },
        {
            "topic_id": "FIN020",
            "topic": "Liquidity: Why Easy Access to Money Matters",
            "category": "Money Fundamentals",
            "difficulty_level": 1,
            "audience": "absolute beginners",
            "key_learning_objective": "Explain liquidity and why keeping some wealth in liquid form is essential for financial health",
            "prerequisites": "FIN010",
        },

        # ── Level 2: Personal Finance (FIN021–FIN040) ─────────────────────
        {
            "topic_id": "FIN021",
            "topic": "How Credit Cards Work: Benefits, Risks, and Traps",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Explain credit card mechanics, interest calculations, and the minimum payment trap",
            "prerequisites": "FIN017",
        },
        {
            "topic_id": "FIN022",
            "topic": "CIBIL Score Explained: Why Your Credit Score Is Your Financial Report Card",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Describe what CIBIL score is, what affects it, and how to improve it in India",
            "prerequisites": "FIN021",
        },
        {
            "topic_id": "FIN023",
            "topic": "EMIs Explained: How to Calculate Your Monthly Instalments",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Calculate EMI using the standard formula and show total interest paid over a loan tenure",
            "prerequisites": "FIN005",
        },
        {
            "topic_id": "FIN024",
            "topic": "The Debt Snowball vs Debt Avalanche Method",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Compare two debt-repayment strategies and show which saves more money mathematically",
            "prerequisites": "FIN017",
        },
        {
            "topic_id": "FIN025",
            "topic": "How Income Tax Works in India: Basics Every Earner Must Know",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Explain the Indian income tax slabs, new vs old regime, and who needs to file a return",
            "prerequisites": "FIN002",
        },
        {
            "topic_id": "FIN026",
            "topic": "Section 80C: Tax Deductions That Save You Money Legally",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "salaried professionals",
            "key_learning_objective": "List the key 80C instruments (PPF, ELSS, LIC, EPF) and show how they reduce taxable income",
            "prerequisites": "FIN025",
        },
        {
            "topic_id": "FIN027",
            "topic": "PPF vs FD vs Savings Account: Where Should You Park Your Money?",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Compare PPF, bank FD, and savings account across interest rate, liquidity, and tax treatment",
            "prerequisites": "FIN007",
        },
        {
            "topic_id": "FIN028",
            "topic": "Term Insurance vs Whole Life Insurance: What You Actually Need",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Explain why term insurance is preferred for pure protection and expose the hidden costs of endowment plans",
            "prerequisites": "FIN018",
        },
        {
            "topic_id": "FIN029",
            "topic": "Health Insurance in India: Why It Is Not Optional",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Explain medical inflation, co-pay, sum insured, and why employer cover alone is insufficient",
            "prerequisites": "FIN010",
        },
        {
            "topic_id": "FIN030",
            "topic": "Envelope Budgeting: A Physical Method That Still Works",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "absolute beginners",
            "key_learning_objective": "Walk through the envelope budgeting system and show how it limits overspending in each category",
            "prerequisites": "FIN008",
        },
        {
            "topic_id": "FIN031",
            "topic": "Zero-Based Budgeting: Give Every Rupee a Job",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Demonstrate zero-based budgeting where income minus all allocations equals zero",
            "prerequisites": "FIN008",
        },
        {
            "topic_id": "FIN032",
            "topic": "Lifestyle Inflation: Why a Raise Does Not Always Mean More Savings",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Define lifestyle inflation and show how automatic spending increases consume salary hikes",
            "prerequisites": "FIN013",
        },
        {
            "topic_id": "FIN033",
            "topic": "The Cost of Waiting: Why Starting to Save Early Changes Everything",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Use compound interest to show how a 25-year-old investor outperforms a 35-year-old with the same total invested",
            "prerequisites": "FIN006",
        },
        {
            "topic_id": "FIN034",
            "topic": "Common Money Mistakes Young Indians Make",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Identify the top 5 financial mistakes (no budget, no emergency fund, lifestyle EMIs, no insurance, no investing) with fixes",
            "prerequisites": "FIN010",
        },
        {
            "topic_id": "FIN035",
            "topic": "EPF and NPS: India's Retirement Savings Frameworks",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "salaried professionals",
            "key_learning_objective": "Explain EPF (Employee Provident Fund) and NPS (National Pension System) benefits, withdrawals, and tax treatment",
            "prerequisites": "FIN026",
        },
        {
            "topic_id": "FIN036",
            "topic": "RBI and the Role of India's Central Bank",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Describe what the Reserve Bank of India does: monetary policy, currency issuance, banking regulation",
            "prerequisites": "FIN016",
        },
        {
            "topic_id": "FIN037",
            "topic": "Digital Payments in India: UPI, NEFT, RTGS, and IMPS",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "absolute beginners",
            "key_learning_objective": "Differentiate UPI, NEFT, RTGS, and IMPS by speed, limits, and appropriate use cases",
            "prerequisites": "FIN001",
        },
        {
            "topic_id": "FIN038",
            "topic": "Financial Fraud and Scams: How to Protect Your Money",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "absolute beginners",
            "key_learning_objective": "Identify common Indian financial scams (Ponzi, phishing, UPI fraud) and explain prevention steps",
            "prerequisites": "FIN001",
        },
        {
            "topic_id": "FIN039",
            "topic": "How to Read Your Bank Statement",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "absolute beginners",
            "key_learning_objective": "Walk through a sample bank statement: debits, credits, charges, and how to spot errors",
            "prerequisites": "FIN016",
        },
        {
            "topic_id": "FIN040",
            "topic": "Building a Financial Plan: A Step-by-Step Framework",
            "category": "Personal Finance",
            "difficulty_level": 2,
            "audience": "young adults",
            "key_learning_objective": "Create a 5-step personal financial plan: assess, budget, insure, save, invest — with Indian context",
            "prerequisites": "FIN018",
        },

        # ── Level 3: Investing Fundamentals (FIN041–FIN060) ───────────────
        {
            "topic_id": "FIN041",
            "topic": "What Is the Stock Market and How Does It Work?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain what stocks are, how exchanges (NSE/BSE) work, and what drives share prices",
            "prerequisites": "FIN007",
        },
        {
            "topic_id": "FIN042",
            "topic": "How to Buy Your First Stock in India",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Walk through opening a demat account, placing a buy order, and understanding settlement",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN043",
            "topic": "What Are Mutual Funds and Why Do Millions of Indians Use Them?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain how mutual funds pool money, the role of an AMC, and the meaning of NAV",
            "prerequisites": "FIN007",
        },
        {
            "topic_id": "FIN044",
            "topic": "SIP: The Habit That Builds Wealth Automatically",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Show how a ₹5,000 monthly SIP over 20 years grows with rupee-cost averaging",
            "prerequisites": "FIN043",
        },
        {
            "topic_id": "FIN045",
            "topic": "Index Funds: The Simplest Way to Invest in India's Growth",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain what Nifty 50 index funds are, their low costs, and why most active funds underperform over time",
            "prerequisites": "FIN043",
        },
        {
            "topic_id": "FIN046",
            "topic": "What Are ETFs and How Do They Differ From Mutual Funds?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Compare ETFs and mutual funds on liquidity, expense ratio, trading mechanism, and tax treatment",
            "prerequisites": "FIN045",
        },
        {
            "topic_id": "FIN047",
            "topic": "What Are Bonds and How Do They Work?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain bonds as fixed-income instruments: coupon, face value, maturity, and yield",
            "prerequisites": "FIN005",
        },
        {
            "topic_id": "FIN048",
            "topic": "Equity vs Debt: Choosing the Right Investment for Your Goal",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Compare equity and debt instruments across risk, return, and time horizon for Indian investors",
            "prerequisites": "FIN047",
        },
        {
            "topic_id": "FIN049",
            "topic": "What Is Diversification and Why Does It Reduce Risk?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Show numerically how diversifying across asset classes and sectors reduces portfolio volatility",
            "prerequisites": "FIN048",
        },
        {
            "topic_id": "FIN050",
            "topic": "Risk vs Return: The Fundamental Trade-Off in Investing",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain the risk-return spectrum from savings accounts to small-cap stocks with Indian examples",
            "prerequisites": "FIN007",
        },
        {
            "topic_id": "FIN051",
            "topic": "Understanding Mutual Fund Categories: Equity, Debt, and Hybrid",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Categorise SEBI-defined fund types and match them to appropriate investor risk profiles",
            "prerequisites": "FIN043",
        },
        {
            "topic_id": "FIN052",
            "topic": "What Is an Expense Ratio and Why Does It Matter?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Show compounding impact of a 0.1% vs 1.5% expense ratio over 20 years on ₹1 lakh invested",
            "prerequisites": "FIN043",
        },
        {
            "topic_id": "FIN053",
            "topic": "Direct vs Regular Mutual Funds: Which Should You Choose?",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Quantify the long-term wealth difference between direct and regular plans using real expense ratios",
            "prerequisites": "FIN052",
        },
        {
            "topic_id": "FIN054",
            "topic": "Sovereign Gold Bonds: A Smarter Way to Invest in Gold",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Compare SGBs with physical gold and Gold ETFs across cost, returns, and safety for Indian investors",
            "prerequisites": "FIN046",
        },
        {
            "topic_id": "FIN055",
            "topic": "What Is a Demat Account? Everything You Need to Know",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain the role of NSDL/CDSL, the demat account structure, and charges to watch for",
            "prerequisites": "FIN042",
        },
        {
            "topic_id": "FIN056",
            "topic": "Capital Gains Tax in India: Short-Term vs Long-Term",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain STCG and LTCG tax rates for equity and debt investments with current Indian tax rules",
            "prerequisites": "FIN025",
        },
        {
            "topic_id": "FIN057",
            "topic": "ELSS: Tax-Saving Mutual Funds That Also Grow Your Wealth",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "salaried professionals",
            "key_learning_objective": "Show how ELSS combines Section 80C tax savings with equity growth potential vs PPF and NSC",
            "prerequisites": "FIN026",
        },
        {
            "topic_id": "FIN058",
            "topic": "Understanding Investment Risk Types: Market, Credit, Liquidity",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Define market risk, credit risk, and liquidity risk with practical Indian examples for each",
            "prerequisites": "FIN050",
        },
        {
            "topic_id": "FIN059",
            "topic": "What Is the Nifty 50 and the Sensex? India's Market Barometers",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Explain how the Nifty 50 and Sensex are constructed, what they measure, and how to interpret their movements",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN060",
            "topic": "Rebalancing Your Portfolio: Why and How to Do It",
            "category": "Investing Fundamentals",
            "difficulty_level": 3,
            "audience": "beginner investors",
            "key_learning_objective": "Define portfolio rebalancing, explain drift, and demonstrate an annual rebalancing example",
            "prerequisites": "FIN049",
        },

        # ── Level 4: Markets and Economics (FIN061–FIN080) ────────────────
        {
            "topic_id": "FIN061",
            "topic": "What Is GDP and Why Should Investors Care?",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain GDP, its components, India's GDP growth trend, and the link between GDP and stock market returns",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN062",
            "topic": "How RBI's Repo Rate Affects Your Loans and Investments",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Trace the transmission from RBI repo rate changes to home loan EMIs, FD rates, and equity valuations",
            "prerequisites": "FIN036",
        },
        {
            "topic_id": "FIN063",
            "topic": "Inflation and Interest Rates: The Invisible Hand of the Economy",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain the relationship between inflation, central bank policy, and the impact on bonds and equities",
            "prerequisites": "FIN004",
        },
        {
            "topic_id": "FIN064",
            "topic": "What Is Market Capitalisation and Why It Classifies Stocks",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Define market cap (price × shares), distinguish large/mid/small caps, and explain their risk profiles",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN065",
            "topic": "Bull Markets and Bear Markets: What They Mean for You",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Define bull and bear markets, show historical Indian examples, and explain appropriate investor behaviour in each",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN066",
            "topic": "Economic Cycles: Expansion, Peak, Recession, Recovery",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Describe the four phases of an economic cycle and how different asset classes typically perform in each",
            "prerequisites": "FIN061",
        },
        {
            "topic_id": "FIN067",
            "topic": "Foreign Institutional Investors: How FIIs Move Indian Markets",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain what FIIs are, how their buying/selling affects Nifty levels, and how to read FII flow data",
            "prerequisites": "FIN059",
        },
        {
            "topic_id": "FIN068",
            "topic": "Currency and Rupee: How Exchange Rates Affect Your Investments",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain USD/INR exchange rate drivers and their impact on imports, exports, IT stocks, and oil prices",
            "prerequisites": "FIN004",
        },
        {
            "topic_id": "FIN069",
            "topic": "Reading a Company's Quarterly Results",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Interpret key quarterly result metrics: revenue, EBITDA, PAT, EPS, and guidance — using a real Nifty company example format",
            "prerequisites": "FIN064",
        },
        {
            "topic_id": "FIN070",
            "topic": "P/E Ratio: The Most Watched Stock Valuation Metric",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Calculate P/E ratio, explain trailing vs forward P/E, and contextualise Nifty 50's historical P/E range",
            "prerequisites": "FIN069",
        },
        {
            "topic_id": "FIN071",
            "topic": "P/B Ratio: Valuing Stocks Relative to Book Value",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Define P/B ratio, explain book value, and show when P/B is particularly useful (banking stocks)",
            "prerequisites": "FIN070",
        },
        {
            "topic_id": "FIN072",
            "topic": "Dividend Investing: Earning While You Hold",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain dividends, dividend yield, payout ratio, and how dividend income is taxed in India",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN073",
            "topic": "Bond Yields and Prices: The Inverse Relationship Explained",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Prove with arithmetic why bond prices fall when yields rise and what this means for debt fund investors",
            "prerequisites": "FIN047",
        },
        {
            "topic_id": "FIN074",
            "topic": "Crude Oil Prices and the Indian Economy",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain India's oil import dependence, the CAD impact of rising crude, and which sectors benefit or suffer",
            "prerequisites": "FIN068",
        },
        {
            "topic_id": "FIN075",
            "topic": "What Is the Union Budget and Why Markets React to It",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain what the Indian Union Budget covers: fiscal deficit, capital expenditure, tax changes, and market impact",
            "prerequisites": "FIN061",
        },
        {
            "topic_id": "FIN076",
            "topic": "Sector Rotation: How Money Moves Through the Economy",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain sector rotation theory and which sectors typically outperform at different stages of an economic cycle",
            "prerequisites": "FIN066",
        },
        {
            "topic_id": "FIN077",
            "topic": "What Is a Stock Split and a Bonus Issue?",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Explain stock splits and bonus shares — why companies do them and what happens to your holdings",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN078",
            "topic": "IPO Investing: How to Evaluate a Company Going Public",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Walk through the IPO process in India: DRHP, price band, allotment, listing, and common red flags",
            "prerequisites": "FIN042",
        },
        {
            "topic_id": "FIN079",
            "topic": "Fiscal Deficit: What It Means When a Government Spends More Than It Earns",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Define fiscal deficit, explain how it is financed (government bonds), and the macroeconomic consequences",
            "prerequisites": "FIN075",
        },
        {
            "topic_id": "FIN080",
            "topic": "Technical Analysis Basics: Support, Resistance, and Trends",
            "category": "Markets and Economics",
            "difficulty_level": 4,
            "audience": "intermediate investors",
            "key_learning_objective": "Introduce support/resistance levels, uptrends/downtrends, and why many traders use charts — with caveats",
            "prerequisites": "FIN059",
        },

        # ── Level 5: Advanced Finance (FIN081–FIN100) ─────────────────────
        {
            "topic_id": "FIN081",
            "topic": "Reading a Balance Sheet: Assets, Liabilities, and Equity",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Walk through a simplified balance sheet using a real Indian company format and identify key health signals",
            "prerequisites": "FIN069",
        },
        {
            "topic_id": "FIN082",
            "topic": "Reading a Profit and Loss Statement",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Interpret revenue, COGS, gross margin, EBITDA, depreciation, interest, tax, and net profit line by line",
            "prerequisites": "FIN081",
        },
        {
            "topic_id": "FIN083",
            "topic": "Cash Flow Statement: The Truth Behind the Numbers",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Explain operating, investing, and financing cash flows and why free cash flow matters more than reported profit",
            "prerequisites": "FIN082",
        },
        {
            "topic_id": "FIN084",
            "topic": "What Is EBITDA and Why Do Analysts Love It?",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Define EBITDA, explain EV/EBITDA, and discuss its usefulness and limitations in Indian company analysis",
            "prerequisites": "FIN082",
        },
        {
            "topic_id": "FIN085",
            "topic": "Return on Equity (ROE) and Return on Capital Employed (ROCE)",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Calculate ROE and ROCE, explain what they reveal about management efficiency, and identify red flags",
            "prerequisites": "FIN081",
        },
        {
            "topic_id": "FIN086",
            "topic": "Discounted Cash Flow: The Gold Standard of Valuation",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Build a simple DCF model using projected free cash flows and a discount rate to estimate intrinsic value",
            "prerequisites": "FIN014",
        },
        {
            "topic_id": "FIN087",
            "topic": "Moat: How to Identify a Company's Competitive Advantage",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Explain economic moats (brand, cost, network, switching, efficient scale) with Indian company examples",
            "prerequisites": "FIN085",
        },
        {
            "topic_id": "FIN088",
            "topic": "Debt-to-Equity Ratio: How Much Debt Is Too Much?",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Calculate D/E ratio, explain appropriate ranges by sector, and identify overleveraged companies",
            "prerequisites": "FIN081",
        },
        {
            "topic_id": "FIN089",
            "topic": "What Are Options and How Do They Work?",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Define call and put options, explain premium, strike price, and expiry — with an F&O example from NSE",
            "prerequisites": "FIN041",
        },
        {
            "topic_id": "FIN090",
            "topic": "Futures Contracts: Locking in Prices for the Future",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Explain how futures contracts work, margin requirements, rollover, and their use in hedging vs speculation",
            "prerequisites": "FIN089",
        },
        {
            "topic_id": "FIN091",
            "topic": "Leverage in Investing: Amplifying Gains and Losses",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Quantify how leverage multiplies both returns and losses and why retail investors must treat it with extreme caution",
            "prerequisites": "FIN090",
        },
        {
            "topic_id": "FIN092",
            "topic": "Portfolio Allocation: Building a Balanced Investment Portfolio",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Design an age-appropriate asset allocation model across equity, debt, gold, and real estate for Indian investors",
            "prerequisites": "FIN060",
        },
        {
            "topic_id": "FIN093",
            "topic": "Behavioural Finance: Why Investors Make Irrational Decisions",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Explain loss aversion, anchoring, herding, and recency bias — and how they destroy investor returns",
            "prerequisites": "FIN050",
        },
        {
            "topic_id": "FIN094",
            "topic": "What Is Alpha and Beta in Portfolio Management?",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Define alpha (excess return vs benchmark) and beta (market sensitivity) and show how to use them to evaluate a fund",
            "prerequisites": "FIN049",
        },
        {
            "topic_id": "FIN095",
            "topic": "Sharpe Ratio: Measuring Risk-Adjusted Returns",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Calculate and interpret the Sharpe ratio and show why it is a better comparison tool than raw returns",
            "prerequisites": "FIN094",
        },
        {
            "topic_id": "FIN096",
            "topic": "How to Do Fundamental Analysis: A Complete Framework",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Present a structured fundamental analysis framework: industry analysis, competitive position, financials, and valuation",
            "prerequisites": "FIN087",
        },
        {
            "topic_id": "FIN097",
            "topic": "REITs in India: Investing in Real Estate Without Buying Property",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Explain SEBI-regulated Indian REITs: structure, income distribution, taxation, and how to invest",
            "prerequisites": "FIN046",
        },
        {
            "topic_id": "FIN098",
            "topic": "Credit Rating Agencies: What AAA, AA, and Junk Mean",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Explain how CRISIL, ICRA, and CARE rate bonds and companies, and what ratings mean for debt fund investors",
            "prerequisites": "FIN047",
        },
        {
            "topic_id": "FIN099",
            "topic": "Risk Management: Protecting a Portfolio from Downside",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Cover stop-losses, hedging, position sizing, maximum drawdown, and portfolio stress testing",
            "prerequisites": "FIN092",
        },
        {
            "topic_id": "FIN100",
            "topic": "Financial Modeling: Building a Simple Three-Statement Model",
            "category": "Advanced Finance",
            "difficulty_level": 5,
            "audience": "advanced investors",
            "key_learning_objective": "Introduce the concept of linking an income statement, balance sheet, and cash flow statement for valuation purposes",
            "prerequisites": "FIN083",
        },
    ]
    return topics


def _default_settings() -> list[dict[str, str]]:
    return [
        {"setting_key": "publishing_mode",      "setting_value": "test",         "description": "test or production"},
        {"setting_key": "videos_per_day",        "setting_value": "2",            "description": "How many Shorts to publish daily"},
        {"setting_key": "publish_time_1",        "setting_value": "08:00",        "description": "First daily publish time (IST)"},
        {"setting_key": "publish_time_2",        "setting_value": "19:00",        "description": "Second daily publish time (IST)"},
        {"setting_key": "min_queue_buffer",      "setting_value": "3",            "description": "Min VIDEO_READY videos before relaxing production rate"},
        {"setting_key": "auto_approve_scripts",  "setting_value": "false",        "description": "Skip manual script approval (true/false)"},
        {"setting_key": "auto_publish",          "setting_value": "false",        "description": "Fully automatic publishing (true/false)"},
        {"setting_key": "channel_name",          "setting_value": "FinanceSimple","description": "Your YouTube channel name"},
        {"setting_key": "default_language",      "setting_value": "en",           "description": "Default script language"},
    ]


# ── Workbook Creation ──────────────────────────────────────────────────────────

def create_workbook() -> None:
    """
    Create the finance_content_queue.xlsx workbook with ContentQueue and
    Settings worksheets. Safe to re-run: backs up existing file first.
    """
    path: Path = config.EXCEL_FILE

    # Backup existing file safely
    if path.exists():
        backup = path.with_suffix(f".backup_{_ts()}.xlsx")
        shutil.copy2(path, backup)
        logger.info("Backed up existing workbook to %s", backup)

    wb = Workbook()

    # ── ContentQueue sheet ─────────────────────────────────────────────────
    ws = wb.active
    ws.title = "ContentQueue"

    # Header row
    for col_idx, col_name in enumerate(CONTENT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font   = _HEADER_FONT
        cell.fill   = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN
        cell.border = _THIN_BORDER

    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"

    # Data rows
    now = _ts_iso()
    topics = _build_topic_seed()
    for row_idx, t in enumerate(topics, start=2):
        row_data = {c: "" for c in CONTENT_COLUMNS}
        row_data.update({
            "topic_id":              t["topic_id"],
            "topic":                 t["topic"],
            "category":              t["category"],
            "difficulty_level":      t["difficulty_level"],
            "audience":              t["audience"],
            "key_learning_objective": t["key_learning_objective"],
            "prerequisites":         t["prerequisites"],
            "status":                "IDEA",
            "retry_count":           0,
            "created_at":            now,
            "updated_at":            now,
        })
        for col_idx, col_name in enumerate(CONTENT_COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row_data[col_name])
            cell.alignment = Alignment(wrap_text=False, vertical="center")
            cell.border = _THIN_BORDER
            # Color-code by status
            status_val = row_data.get("status", "")
            if status_val in _STATUS_COLORS:
                cell.fill = PatternFill("solid", fgColor=_STATUS_COLORS[status_val])

    # Column widths
    _col_widths = {
        "topic_id": 10, "topic": 40, "category": 20, "difficulty_level": 8,
        "audience": 15, "key_learning_objective": 45, "prerequisites": 15,
        "research_sources": 30, "research_summary": 40, "script": 60,
        "video_title": 40, "video_description": 50, "keywords": 30,
        "estimated_duration": 12, "narration_file": 30, "captions_file": 30,
        "video_file": 30, "scheduled_at": 20, "status": 18,
        "youtube_video_id": 20, "instagram_media_id": 20,
        "published_url_youtube": 35, "published_url_instagram": 35,
        "retry_count": 8, "last_error": 35,
        "created_at": 20, "updated_at": 20,
    }
    for col_idx, col_name in enumerate(CONTENT_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = _col_widths.get(col_name, 15)

    # ── Settings sheet ─────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Settings")
    for col_idx, col_name in enumerate(SETTINGS_COLUMNS, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=col_name)
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN
        cell.border    = _THIN_BORDER

    ws2.row_dimensions[1].height = 30
    for row_idx, s in enumerate(_default_settings(), start=2):
        for col_idx, col_name in enumerate(SETTINGS_COLUMNS, start=1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=s[col_name])
            cell.alignment = Alignment(vertical="center")
            cell.border    = _THIN_BORDER

    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["B"].width = 20
    ws2.column_dimensions["C"].width = 50

    wb.save(path)
    logger.info("Workbook saved: %s (%d topics)", path, len(topics))


# ── Reading ────────────────────────────────────────────────────────────────────

def read_topics() -> list[dict[str, Any]]:
    """Load all rows from the ContentQueue sheet."""
    path: Path = config.EXCEL_FILE
    if not path.exists():
        raise FileNotFoundError(f"Excel workbook not found: {path}")
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb["ContentQueue"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h else "" for h in rows[0]]
    result = []
    for row in rows[1:]:
        record = {headers[i]: (row[i] if i < len(row) else None) for i in range(len(headers))}
        if record.get("topic_id"):
            result.append(record)
    wb.close()
    return result


def update_topic_in_excel(topic_id: str, updates: dict[str, Any]) -> None:
    """
    Safely update fields for a topic in the ContentQueue sheet.
    Backs up the file before writing to prevent corruption.
    """
    path: Path = config.EXCEL_FILE
    if not path.exists():
        raise FileNotFoundError(f"Excel workbook not found: {path}")

    # Safe write: operate on a temp copy first
    tmp = path.with_suffix(".tmp.xlsx")
    shutil.copy2(path, tmp)
    try:
        wb = openpyxl.load_workbook(str(tmp))
        ws = wb["ContentQueue"]
        headers = [c.value for c in ws[1]]

        for row in ws.iter_rows(min_row=2):
            row_topic_id = row[0].value
            if str(row_topic_id) == str(topic_id):
                for field, value in updates.items():
                    if field in headers:
                        col_idx = headers.index(field)
                        row[col_idx].value = value
                        # Re-apply status color
                        if field == "status" and value in _STATUS_COLORS:
                            row[col_idx].fill = PatternFill("solid", fgColor=_STATUS_COLORS[value])
                break

        wb.save(tmp)
        # Atomic replace
        path.unlink()
        tmp.rename(path)
        logger.debug("Updated topic %s in Excel: %s", topic_id, list(updates.keys()))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def sync_db_to_excel() -> None:
    """
    Syncs authoritative SQLite database records to the Excel workbook.
    Updates status, video URLs, and timestamps for all topics.
    """
    path: Path = config.EXCEL_FILE
    if not path.exists():
        logger.warning("Excel file %s does not exist, skipping sync", path)
        return

    from storage import database
    topics = database.list_topics()
    tmp = path.with_suffix(".tmp.xlsx")
    shutil.copy2(path, tmp)

    try:
        wb = openpyxl.load_workbook(str(tmp))
        ws = wb["ContentQueue"]
        headers = [c.value for c in ws[1]]

        topic_row_map = {}
        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            t_id = row[0].value
            if t_id:
                topic_row_map[str(t_id)] = row_idx

        for t in topics:
            t_id = str(t["topic_id"])
            if t_id not in topic_row_map:
                continue

            r_idx = topic_row_map[t_id]
            status_val = t.get("status", "IDEA")

            # Check for YouTube upload
            yt_upload = database.get_upload_by_topic_platform(t_id, "youtube")
            yt_id = yt_upload["video_id"] if yt_upload else ""
            yt_url = yt_upload["published_url"] if yt_upload else ""

            updates = {
                "status": status_val,
                "youtube_video_id": yt_id,
                "published_url_youtube": yt_url,
                "updated_at": t.get("updated_at", ""),
            }

            for field, val in updates.items():
                if field in headers and val:
                    c_idx = headers.index(field) + 1
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    if field == "status" and val in _STATUS_COLORS:
                        cell.fill = PatternFill("solid", fgColor=_STATUS_COLORS[val])

        wb.save(tmp)
        path.unlink()
        tmp.rename(path)
        logger.info("Successfully synced SQLite state to Excel (%d topics)", len(topics))

    except Exception:
        tmp.unlink(missing_ok=True)
        raise



# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
