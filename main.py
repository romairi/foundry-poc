from agents.corporate_agent import CorporateAgent
from agents.travel_agent import TravelAgent


def main():
    print("=" * 55)
    print("  Azure AI Foundry — Multi-Agent Demo")
    print("=" * 55)

    corporate = CorporateAgent().create()
    travel = TravelAgent().create()

    try:
        scenarios = [
            (travel, "What's the weather in Tel Aviv? I'm flying there next week."),
            (corporate, "How much is 15% tip on 850 shekels?"),
            (corporate, "What's the shuttle schedule?"),
            (corporate, "I spent 200 shekels on lunch. What's the expense procedure and how much is that in dollars (rate 0.27)?"),
            (travel, "Should I pack a jacket for Moscow?"),
        ]

        for agent, question in scenarios:
            print(f"\n{'─' * 55}")
            print(f"🤖 Agent: {agent.name}")
            print(f"👤 User: {question}")
            response = agent.ask(question)
            print(f"💬 Response: {response}")

    finally:
        corporate.cleanup()
        travel.cleanup()
        print("\n✓ All agents deleted. Done.")


if __name__ == "__main__":
    main()
