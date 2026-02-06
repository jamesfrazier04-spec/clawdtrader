"""
Clawdbot Strategy Chat
Interactive chat interface for upgrading and refining trading strategies.
Chat with the AI to discuss strategy improvements, which are saved to memory.
"""

import os
import re
import sys
from datetime import datetime
from typing import List, Dict, Optional

from dotenv import load_dotenv

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

load_dotenv()

from openai import OpenAI
from tools.memory_tools import (
    save_strategy_insight,
    format_insights_for_prompt,
    get_memory_stats,
    save_conversation,
    get_trade_outcomes,
    get_win_rate,
    get_memory_context_for_prompt
)

# Initialize OpenAI client
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_API_BASE")
)

MODEL = os.getenv("STRATEGY_CHAT_MODEL", "gpt-4o")

SYSTEM_PROMPT = """You are Clawdbot's Strategy Advisor - an expert AI trading strategist.

Your role is to help improve and refine trading strategies through conversation.
You have access to the trader's memory of past insights and performance.

## CURRENT MEMORY STATE:
{memory_context}

## YOUR CAPABILITIES:
1. Analyze proposed strategy changes - discuss pros, cons, and risks
2. Suggest improvements based on past performance
3. Help formalize trading rules
4. Review and critique current approaches
5. Extract learnings from past trades

## IMPORTANT BEHAVIORS:
- When the user proposes a valuable insight or strategy rule, save it by outputting:
  <SAVE_INSIGHT>the insight to save</SAVE_INSIGHT>

- When tagging an insight, use this format:
  <SAVE_INSIGHT tags="tag1,tag2">the insight</SAVE_INSIGHT>

- Be specific and actionable in your advice
- Reference past performance data when relevant
- Ask clarifying questions when needed
- Challenge assumptions constructively

## EXAMPLE INSIGHTS TO SAVE:
- "Never hold NVDA through earnings - too volatile"
- "Buy tech dips on Monday mornings - historically recovers by Wednesday"
- "Limit single position to 20% of portfolio to manage risk"
- "Cut losses at -5% - don't hold hoping for recovery"

Start by greeting the user and asking what aspect of the strategy they'd like to discuss.
"""


def extract_insights_from_response(response: str) -> List[Dict[str, str]]:
    """Extract insights marked for saving from the AI response."""
    insights = []

    # Pattern: <SAVE_INSIGHT>content</SAVE_INSIGHT> or <SAVE_INSIGHT tags="...">content</SAVE_INSIGHT>
    pattern = r'<SAVE_INSIGHT(?:\s+tags="([^"]*)")?\s*>(.*?)</SAVE_INSIGHT>'
    matches = re.findall(pattern, response, re.DOTALL)

    for tags_str, insight in matches:
        tags = [t.strip() for t in tags_str.split(",")] if tags_str else []
        insights.append({
            "insight": insight.strip(),
            "tags": tags
        })

    return insights


def clean_response_for_display(response: str) -> str:
    """Remove SAVE_INSIGHT tags from response for cleaner display."""
    # Remove the tags but keep indication that insight was saved
    pattern = r'<SAVE_INSIGHT(?:\s+tags="[^"]*")?\s*>(.*?)</SAVE_INSIGHT>'
    cleaned = re.sub(pattern, r'[Saved: \1]', response, flags=re.DOTALL)
    return cleaned


def chat_loop():
    """Main interactive chat loop."""
    print("\n" + "=" * 60)
    print("   CLAWDBOT STRATEGY CHAT")
    print("   Discuss and improve your trading strategies")
    print("=" * 60)
    print("\nCommands:")
    print("  'quit' or 'exit' - Exit chat")
    print("  'stats' - Show memory statistics")
    print("  'insights' - Show current strategy insights")
    print("  'performance' - Show trading performance")
    print("  'clear' - Clear conversation (start fresh)")
    print("  'save' - Save this conversation to memory")
    print("-" * 60 + "\n")

    # Build system prompt with current memory
    memory_context = get_memory_context_for_prompt()
    system_prompt = SYSTEM_PROMPT.format(memory_context=memory_context)

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]

    # Get initial greeting
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7
        )
        greeting = response.choices[0].message.content
        print(f"Clawdbot: {greeting}\n")
        messages.append({"role": "assistant", "content": greeting})
    except Exception as e:
        print(f"Error connecting to AI: {e}")
        print("Make sure OPENAI_API_KEY is set in your .env file")
        return

    insights_saved_this_session = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.lower() in ['quit', 'exit']:
            # Offer to save conversation
            if len(messages) > 2:
                save_choice = input("\nSave this conversation to memory? (y/n): ").strip().lower()
                if save_choice == 'y':
                    summary = input("Brief summary of this chat: ").strip()
                    save_conversation(
                        messages=messages[1:],  # Exclude system prompt
                        summary=summary,
                        insights_extracted=[i["insight"] for i in insights_saved_this_session]
                    )
                    print("Conversation saved!")
            print("\nGoodbye!")
            break

        elif user_input.lower() == 'stats':
            stats = get_memory_stats()
            print(f"\n--- Memory Statistics ---")
            print(f"Strategy insights: {stats['strategy_insights']}")
            print(f"Trade outcomes: {stats['trade_outcomes']}")
            print(f"Saved conversations: {stats['conversations']}")
            if stats['win_rate']['total_trades'] > 0:
                print(f"Win rate: {stats['win_rate']['win_rate']:.1f}%")
            print("-" * 25 + "\n")
            continue

        elif user_input.lower() == 'insights':
            print(f"\n--- Current Strategy Insights ---")
            print(format_insights_for_prompt())
            print("-" * 35 + "\n")
            continue

        elif user_input.lower() == 'performance':
            win_stats = get_win_rate()
            print(f"\n--- Trading Performance ---")
            print(f"Total trades: {win_stats['total_trades']}")
            print(f"Wins: {win_stats['wins']}")
            print(f"Losses: {win_stats['losses']}")
            print(f"Neutral: {win_stats['neutral']}")
            print(f"Win rate: {win_stats['win_rate']:.1f}%")

            # Show recent outcomes
            recent = get_trade_outcomes(n=5)
            if recent:
                print("\nRecent trades:")
                for t in recent[-5:]:
                    outcome_emoji = {"win": "+", "loss": "-", "neutral": "=", "pending": "?"}
                    emoji = outcome_emoji.get(t.get("outcome", "?"), "?")
                    pct = t.get('profit_pct') or 0
                    print(f"  [{emoji}] {t['symbol']} {t['action']} - {pct:.1f}%")
            print("-" * 27 + "\n")
            continue

        elif user_input.lower() == 'clear':
            messages = [{"role": "system", "content": system_prompt}]
            insights_saved_this_session = []
            print("\nConversation cleared. Starting fresh.\n")
            continue

        elif user_input.lower() == 'save':
            if len(messages) > 2:
                summary = input("Brief summary of this chat: ").strip()
                save_conversation(
                    messages=messages[1:],
                    summary=summary,
                    insights_extracted=[i["insight"] for i in insights_saved_this_session]
                )
                print("Conversation saved!\n")
            else:
                print("Not enough conversation to save.\n")
            continue

        # Regular chat message
        messages.append({"role": "user", "content": user_input})

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7
            )
            reply = response.choices[0].message.content

            # Extract and save any insights
            insights = extract_insights_from_response(reply)
            for insight_data in insights:
                save_strategy_insight(
                    insight=insight_data["insight"],
                    tags=insight_data["tags"],
                    source="chat"
                )
                insights_saved_this_session.append(insight_data)

            # Clean and display response
            display_reply = clean_response_for_display(reply)
            print(f"\nClawdbot: {display_reply}\n")

            messages.append({"role": "assistant", "content": reply})

        except Exception as e:
            print(f"\nError: {e}\n")
            messages.pop()  # Remove the failed user message


def quick_insight(insight: str, tags: Optional[List[str]] = None):
    """
    Quick function to add an insight without full chat.
    Can be called from command line or other scripts.
    """
    save_strategy_insight(
        insight=insight,
        tags=tags or [],
        source="manual"
    )
    print(f"Saved insight: {insight}")


if __name__ == "__main__":
    # Check for command line arguments for quick insight saving
    if len(sys.argv) > 1:
        if sys.argv[1] == "--insight":
            if len(sys.argv) > 2:
                insight_text = " ".join(sys.argv[2:])
                quick_insight(insight_text)
            else:
                print("Usage: python strategy_chat.py --insight <your insight here>")
        elif sys.argv[1] == "--stats":
            stats = get_memory_stats()
            print(f"Strategy insights: {stats['strategy_insights']}")
            print(f"Trade outcomes: {stats['trade_outcomes']}")
            print(f"Win rate: {stats['win_rate']['win_rate']:.1f}%")
        else:
            print("Usage:")
            print("  python strategy_chat.py           # Start interactive chat")
            print("  python strategy_chat.py --insight # Save a quick insight")
            print("  python strategy_chat.py --stats   # Show memory stats")
    else:
        chat_loop()
