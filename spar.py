#!/usr/bin/env python3
"""
SPAR — Two AI agents beat the shit out of ideas until a real gem survives.
Then a VC tries to kill it. If the VC can't, you've got something.
Built by ENI for LO. Don't touch my coffee.

Usage:
    python spar.py "Should my spy protag betray his lover in Act 3?"
    python spar.py "Give me a fresh angle on a heist story" --rounds 10
    python spar.py "Pitch me an erotica premise involving a librarian" --rounds 5
    python spar.py "devops business idea in finance" --min-verdict brilliant
    python spar.py "some idea" --vc-rounds 3  (max VC rejection cycles, default 2)
"""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import (
    ResultMessage, AssistantMessage, TextBlock, ToolUseBlock, ToolResultBlock,
    ThinkingConfigEnabled
)
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console(width=100)

# ─── CONFIG ───────────────────────────────────────────────────────────────────

ROUNDS = int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 12
VC_MAX_REJECTIONS = int(sys.argv[sys.argv.index("--vc-rounds") + 1]) if "--vc-rounds" in sys.argv else 2
EXTRA_ROUNDS_PER_REJECTION = 4  # extra sparring rounds after each VC rejection
WORK_DIR = Path(__file__).parent
OUTPUT_DIR = WORK_DIR / "sparring_sessions"
OUTPUT_DIR.mkdir(exist_ok=True)

MIN_VERDICT = "brilliant"
if "--min-verdict" in sys.argv:
    v = sys.argv[sys.argv.index("--min-verdict") + 1].lower()
    MIN_VERDICT = v

# ─── PROMPT LOADING ───────────────────────────────────────────────────────────

PROMPTS_DIR = WORK_DIR / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt from prompts/ directory, injecting research protocol."""
    prompt_file = PROMPTS_DIR / f"{name}.md"
    research_file = PROMPTS_DIR / "research_protocol.md"

    prompt = prompt_file.read_text()
    research = research_file.read_text()

    # Inject research protocol where placeholder exists
    if "{RESEARCH_PROTOCOL}" in prompt:
        prompt = prompt.replace("{RESEARCH_PROTOCOL}", research)

    return prompt


RAZOR = load_prompt("razor")
EMBER = load_prompt("ember")
JUDGE = load_prompt("judge")
VC = load_prompt("viper")

# ─── STYLE CONFIG ─────────────────────────────────────────────────────────────

AGENT_STYLES = {
    "RAZOR": {"border": "red", "icon": "🔪", "title_style": "bold red"},
    "EMBER": {"border": "yellow", "icon": "🔥", "title_style": "bold yellow"},
    "JUDGE": {"border": "cyan", "icon": "⚖️ ", "title_style": "bold cyan"},
    "VIPER": {"border": "green", "icon": "🐍", "title_style": "bold green"},
    "PITCH": {"border": "magenta", "icon": "📋", "title_style": "bold magenta"},
}

DIM = "\033[2m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


def parse_verdict(response: str) -> str:
    """Extract verdict/decision from ONLY the VERDICT:/DECISION: line."""
    for line in response.split("\n"):
        line_clean = line.strip()
        # JUDGE verdict
        match = re.match(
            r'^VERDICT:\s*\*{0,2}\s*(GARBAGE|WEAK|PROMISING|STRONG|FUCKING BRILLIANT)\s*\*{0,2}\s*$',
            line_clean, re.IGNORECASE
        )
        if match:
            return match.group(1).upper()
        # VC decision
        match = re.match(
            r'^DECISION:\s*\*{0,2}\s*(INVEST|PASS|CONDITIONAL(?:\s*[—\-]\s*NEEDS MORE WORK)?)\s*\*{0,2}\s*$',
            line_clean, re.IGNORECASE
        )
        if match:
            raw = match.group(1).upper().strip()
            if raw.startswith("CONDITIONAL"):
                return "CONDITIONAL"
            return raw
    return "UNPARSEABLE"


def render_agent(label: str, text: str):
    """Render agent output as a rich panel with markdown formatting."""
    style = AGENT_STYLES.get(label, {"border": "white", "icon": "?", "title_style": "bold"})
    md = Markdown(text)
    panel = Panel(
        md,
        title=f"{style['icon']} {label}",
        title_align="left",
        border_style=style["border"],
        padding=(1, 2),
    )
    console.print(panel)

# ─── ENGINE ───────────────────────────────────────────────────────────────────

async def ask_agent(system_prompt: str, prompt: str, label: str, color: str) -> str:
    """Fire a query, stream tool usage live, collect final text."""
    result_text = ""
    all_text_blocks = []

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system_prompt,
            permission_mode="bypassPermissions",
            cwd=str(WORK_DIR),
            max_turns=40,
            model="claude-opus-4-6",
            thinking=ThinkingConfigEnabled(type="enabled", budget_tokens=10000),
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    tool_name = block.name
                    tool_input = block.input
                    if tool_name in ("WebSearch", "WebFetch"):
                        search_term = tool_input.get("query", tool_input.get("url", tool_input.get("prompt", "")))
                        print(f"{DIM}{MAGENTA}    [{label} searching: {search_term[:120]}]{RESET}")
                    elif tool_name in ("Read", "Glob", "Grep"):
                        target = tool_input.get("file_path", tool_input.get("pattern", tool_input.get("query", "")))
                        print(f"{DIM}{MAGENTA}    [{label} reading: {target[:120]}]{RESET}")
                    else:
                        print(f"{DIM}{MAGENTA}    [{label} using {tool_name}]{RESET}")
                elif isinstance(block, TextBlock):
                    all_text_blocks.append(block.text)

        elif isinstance(message, ResultMessage):
            if message.result:
                result_text = message.result

    if not result_text and all_text_blocks:
        result_text = "\n".join(all_text_blocks)

    return result_text.strip() if result_text else "(no response)"


# ─── SPARRING PHASE ──────────────────────────────────────────────────────────

async def run_sparring(premise: str, transcript: list, start_round: int,
                       num_rounds: int, razor_history: str, ember_history: str,
                       judge_feedback: str, vc_rejection: str = "") -> tuple:
    """Run sparring rounds. Returns (verdict, razor_history, ember_history, judge_feedback, final_round)."""
    verdict = "WEAK"
    vc_injection_done = False

    for round_num in range(start_round, start_round + num_rounds):
        console.print()
        console.rule(f"[bold]Round {round_num}[/bold]", style="dim")
        console.print()
        transcript.append(f"── ROUND {round_num} ──\n")

        # Full conversation context — everyone sees everything
        convo_so_far = "\n\n".join(transcript)

        # ── EMBER goes FIRST (builder pitches, then destroyer attacks) ──
        if round_num == 1:
            ember_prompt = (
                f"Someone pitched this idea: \"{premise}\"\n\n"
                f"RESEARCH the space. Find the real pain, the real market, the real "
                f"customers. Build the BEST possible version of this idea — specific "
                f"customer, specific product, specific pricing, specific moat. "
                f"Back everything with evidence. Make it so good that RAZOR has to "
                f"actually work to kill it."
            )
        else:
            ember_prompt = (
                f"Original premise: \"{premise}\"\n\n"
                f"Here is the FULL conversation so far (all rounds, all agents):\n"
                f"---\n{convo_so_far}\n---\n\n"
            )
            if vc_rejection and not vc_injection_done:
                ember_prompt += (
                    f"\nA VC (VIPER) REJECTED the idea with this feedback:\n"
                    f"---\n{vc_rejection}\n---\n\n"
                    f"The VC's objections are CRITICAL. You must address EVERY concern "
                    f"they raised — either by solving it or by pivoting away from it. "
                    f"Do NOT ignore the VC feedback.\n\n"
                )
                vc_injection_done = True  # Both agents got it, stop injecting
            ember_prompt += (
                f"Round {round_num}. RESEARCH and BUILD. Review the full history — "
                f"build on what survived, don't rehash dead ideas. Address RAZOR's "
                f"latest attacks — counter with evidence or PIVOT. "
                f"Every claim needs a source."
            )

        ember_response = await ask_agent(EMBER, ember_prompt, "EMBER", "yellow")
        ember_history = ember_response
        render_agent("EMBER", ember_response)
        transcript.append(f"EMBER:\n{ember_response}\n")

        # ── RAZOR goes SECOND (destroyer attacks EMBER's pitch) ──
        # Rebuild convo context including EMBER's pitch from this round
        convo_so_far = "\n\n".join(transcript)

        if round_num == 1:
            razor_prompt = (
                f"Original premise: \"{premise}\"\n\n"
                f"EMBER just pitched this idea:\n\n"
                f"---\n{ember_response}\n---\n\n"
                f"DESTROY IT. Search the web for competitors, failed attempts, "
                f"market data that contradicts this. Find the fatal flaw. "
                f"If you can't find one, propose a CONTRADICTING alternative direction."
            )
        else:
            razor_prompt = (
                f"Original premise: \"{premise}\"\n\n"
                f"Here is the conversation so far:\n"
                f"---\n{convo_so_far}\n---\n\n"
            )
            if vc_rejection and not vc_injection_done:
                razor_prompt += (
                    f"\nA VC (VIPER) REJECTED the idea with this feedback:\n"
                    f"---\n{vc_rejection}\n---\n\n"
                    f"Use the VC's objections as NEW ammunition. Find evidence that "
                    f"supports or contradicts the VC's concerns. The idea must address "
                    f"EVERY issue the VC raised or it's dead.\n\n"
                )
            razor_prompt += (
                f"Round {round_num}. RESEARCH and ATTACK. Review the full history — "
                f"don't repeat kills that already landed. Find NEW fatal flaws. "
                f"Search for counter-evidence to EMBER's latest claims. "
                f"If the current direction is dead, propose a CONTRADICTING pivot."
            )

        razor_response = await ask_agent(RAZOR, razor_prompt, "RAZOR", "red")
        razor_history = razor_response
        render_agent("RAZOR", razor_response)
        transcript.append(f"RAZOR:\n{razor_response}\n")

        # ── JUDGE every 2 rounds or last round ──
        if round_num % 2 == 0 or round_num == (start_round + num_rounds - 1):
            full_transcript = "\n\n".join(transcript)
            judge_prompt = (
                f"Sparring transcript (round {round_num}):\n\n"
                f"---\n{full_transcript}\n---\n\n"
                f"Evaluate RUTHLESSLY. Check EVERY hard gate requirement.\n\n"
                f"CRITICAL FORMAT RULE: Your response MUST start with exactly:\n"
                f"VERDICT: [rating]\n"
                f"...on its own line, no markdown, no bold, no asterisks.\n\n"
                f"HARD GATE REMINDERS:\n"
                f"- STRONG requires: named customer segment, researched competitor, "
                f"real numbers, real evidence of pain, round 4+\n"
                f"- FUCKING BRILLIANT requires ALL of STRONG plus: at least ONE real "
                f"human voice (not a market report) wanting this, RAZOR failed to kill "
                f"it, competitive moat stress-tested, 18-month model, data trust problem "
                f"addressed, domain expert hiring plan concrete, round 6+, ZERO critical "
                f"items in STILL NEEDS. If ANY gate fails, verdict is STRONG at best.\n"
                f"- If you gave STRONG last time and same issues remain, DOWNGRADE.\n"
                f"- If agents are agreeing too much, FORCE more conflict.\n"
                f"- If sparring is stale, FORCE A PIVOT.\n"
                f"- Your job is to make this idea EARN its survival. Most ideas don't."
            )

            judge_response = await ask_agent(JUDGE, judge_prompt, "JUDGE", "cyan")
            judge_feedback = judge_response
            render_agent("JUDGE", judge_response)
            transcript.append(f"JUDGE (Round {round_num}):\n{judge_response}\n")

            parsed = parse_verdict(judge_response)

            if parsed == "GARBAGE":
                verdict = "GARBAGE"
                console.print("  [bold red]✗ VERDICT: GARBAGE — KILL IT AND START OVER[/bold red]\n")

            elif parsed == "FUCKING BRILLIANT":
                verdict = "FUCKING BRILLIANT"
                console.print()
                console.print(Panel(
                    "[bold]★ FUCKING BRILLIANT — ADVANCING TO VC REVIEW ★[/bold]",
                    border_style="bold green", padding=(1, 4),
                ))
                return verdict, razor_history, ember_history, judge_feedback, round_num

            elif parsed == "STRONG":
                verdict = "STRONG"
                if MIN_VERDICT == "strong":
                    console.print()
                    console.print(Panel(
                        "[bold]★ STRONG — ADVANCING TO VC REVIEW ★[/bold]",
                        border_style="bold green", padding=(1, 4),
                    ))
                    return verdict, razor_history, ember_history, judge_feedback, round_num
                else:
                    console.print("  [dim]...STRONG but we need FUCKING BRILLIANT. Keep fighting...[/dim]\n")

            elif parsed == "PROMISING":
                verdict = "PROMISING"
                console.print("  [dim]...promising, not there yet. Keep digging...[/dim]\n")

            elif parsed == "WEAK":
                verdict = "WEAK"
                console.print("  [dim]...weak. Sharpen up or pivot...[/dim]\n")

            elif parsed == "UNPARSEABLE":
                console.print("  [dim yellow]...couldn't parse verdict, treating as PROMISING...[/dim yellow]\n")
                verdict = "PROMISING"
        else:
            judge_feedback = ""

    return verdict, razor_history, ember_history, judge_feedback, start_round + num_rounds - 1


# ─── VC REVIEW PHASE ─────────────────────────────────────────────────────────

async def run_vc_review(premise: str, transcript: list, attempt: int) -> tuple:
    """Run VC due diligence. Returns (decision, vc_response)."""

    console.print()
    console.rule(f"[bold green]VC REVIEW — Attempt {attempt}[/bold green]", style="bold green")
    console.print()

    full_transcript = "\n\n".join(transcript)
    vc_prompt = (
        f"A startup idea has survived {len([t for t in transcript if t.startswith('── ROUND')])} "
        f"rounds of adversarial sparring and earned a passing verdict from a strict judge.\n\n"
        f"Original premise: \"{premise}\"\n\n"
        f"Full sparring transcript:\n"
        f"---\n{full_transcript}\n---\n\n"
        f"This is VC review attempt {attempt}. "
    )
    if attempt > 1:
        vc_prompt += (
            f"The idea was PREVIOUSLY REJECTED by you and sent back for more sparring. "
            f"The agents have done additional rounds to address your concerns. "
            f"Evaluate whether the new work ACTUALLY resolves the issues you raised, "
            f"or if they just hand-waved past them. Be HARDER this time — ideas that "
            f"come back without meaningfully improving deserve a PASS, not endless chances.\n\n"
        )
    vc_prompt += (
        f"Run your FULL 8-point due diligence checklist. Search the web for EVERY item. "
        f"Make your investment decision.\n\n"
        f"CRITICAL FORMAT RULE: Your response MUST start with exactly:\n"
        f"DECISION: INVEST\n"
        f"or DECISION: PASS\n"
        f"or DECISION: CONDITIONAL — NEEDS MORE WORK\n"
        f"...on its own line, no markdown, no bold, no asterisks."
    )

    vc_response = await ask_agent(VC, vc_prompt, "VIPER", "green")
    render_agent("VIPER", vc_response)
    transcript.append(f"VIPER (VC Review {attempt}):\n{vc_response}\n")

    decision = parse_verdict(vc_response)
    return decision, vc_response


# ─── FINAL PITCH ──────────────────────────────────────────────────────────────

PITCHER = load_prompt("pitch")


async def run_final_pitch(premise: str, transcript: list) -> str:
    """Generate final pitch summary of the entire session."""

    console.print()
    console.rule("[bold magenta]FINAL PITCH[/bold magenta]", style="bold magenta")
    console.print()

    full_transcript = "\n\n".join(transcript)
    pitch_prompt = (
        f"Original premise: \"{premise}\"\n\n"
        f"Full session transcript:\n"
        f"---\n{full_transcript}\n---\n\n"
        f"Write the FINAL PITCH. Compress everything above into a tight, "
        f"actionable summary. Follow your output format exactly."
    )

    pitch_response = await ask_agent(PITCHER, pitch_prompt, "PITCH", "magenta")
    render_agent("PITCH", pitch_response)
    transcript.append(f"\n{'='*70}")
    transcript.append(f"FINAL PITCH:\n{pitch_response}")

    return pitch_response


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

async def spar(premise: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = premise[:40].replace(" ", "_").replace("?", "").replace("'", "").lower()
    outfile = OUTPUT_DIR / f"spar_{slug}_{timestamp}.txt"

    transcript = []
    transcript.append(f"{'='*70}")
    transcript.append(f"SPARRING SESSION — {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    transcript.append(f"PREMISE: {premise}")
    transcript.append(f"ROUNDS: {ROUNDS} | MIN VERDICT: {MIN_VERDICT.upper()} | VC MAX REJECTIONS: {VC_MAX_REJECTIONS}")
    transcript.append(f"{'='*70}\n")

    console.print()
    console.print(Panel(
        f"[dim]Premise:[/dim] {premise}\n"
        f"[dim]Rounds:[/dim] {ROUNDS} | "
        f"[dim]Exit threshold:[/dim] {MIN_VERDICT.upper()} | "
        f"[dim]VC rejection cycles:[/dim] {VC_MAX_REJECTIONS}",
        title="⚔️  SPARRING SESSION",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))

    # ─── Phase 1: Initial sparring ───
    verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
        premise, transcript,
        start_round=1, num_rounds=ROUNDS,
        razor_history="", ember_history="", judge_feedback=""
    )

    # If sparring didn't reach threshold, save and exit
    threshold_met = (
        (MIN_VERDICT == "strong" and verdict in ("STRONG", "FUCKING BRILLIANT")) or
        (MIN_VERDICT in ("brilliant", "fucking brilliant") and verdict == "FUCKING BRILLIANT")
    )

    if not threshold_met:
        # ─── Final pitch even on failure — the graveyard is valuable ───
        await run_final_pitch(premise, transcript)

        transcript.append(f"\n{'='*70}")
        transcript.append(f"FINAL RESULT: Sparring ended at {verdict} — did not reach VC review")
        transcript.append(f"{'='*70}")
        outfile.write_text("\n".join(transcript))
        console.print()
        console.print(Panel(
            f"[bold]Final Verdict: [red]{verdict}[/red][/bold]\n"
            f"[dim]Did not reach VC review threshold. Transcript saved: {outfile}[/dim]",
            title="SESSION COMPLETE",
            title_align="left",
            border_style="bold white",
            padding=(1, 2),
        ))
        return

    # ─── Phase 2: VC review loop ───
    final_decision = "PASS"
    vc_rejection_feedback = ""

    for vc_attempt in range(1, VC_MAX_REJECTIONS + 2):  # +2 because first attempt isn't a "rejection"
        decision, vc_response = await run_vc_review(premise, transcript, vc_attempt)

        if decision == "INVEST":
            final_decision = "INVEST"
            console.print()
            console.print(Panel(
                "[bold green]💰 DECISION: INVEST — THE VC IS IN 💰[/bold green]",
                border_style="bold green", padding=(1, 4),
            ))
            break

        elif decision == "PASS":
            final_decision = "PASS"
            console.print()
            console.print(Panel(
                "[bold red]✗ DECISION: PASS — THE VC WALKED AWAY[/bold red]",
                border_style="bold red", padding=(1, 4),
            ))

            if vc_attempt <= VC_MAX_REJECTIONS:
                console.print(f"  [dim]VC rejected. Sending back for {EXTRA_ROUNDS_PER_REJECTION} more sparring rounds "
                              f"(rejection {vc_attempt}/{VC_MAX_REJECTIONS})...[/dim]\n")
                vc_rejection_feedback = vc_response

                # Extra sparring rounds to address VC concerns
                verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
                    premise, transcript,
                    start_round=last_round + 1,
                    num_rounds=EXTRA_ROUNDS_PER_REJECTION,
                    razor_history=razor_h, ember_history=ember_h,
                    judge_feedback=judge_fb, vc_rejection=vc_rejection_feedback
                )
            else:
                console.print(f"  [dim]Max VC rejections ({VC_MAX_REJECTIONS}) reached. Ending session.[/dim]\n")
                break

        elif decision == "CONDITIONAL":
            final_decision = "CONDITIONAL"
            console.print()
            console.print(Panel(
                "[bold yellow]⚠ DECISION: CONDITIONAL — NEEDS MORE WORK[/bold yellow]",
                border_style="bold yellow", padding=(1, 4),
            ))

            if vc_attempt <= VC_MAX_REJECTIONS:
                console.print(f"  [dim]VC wants more work. {EXTRA_ROUNDS_PER_REJECTION} more sparring rounds "
                              f"(attempt {vc_attempt}/{VC_MAX_REJECTIONS})...[/dim]\n")
                vc_rejection_feedback = vc_response

                verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
                    premise, transcript,
                    start_round=last_round + 1,
                    num_rounds=EXTRA_ROUNDS_PER_REJECTION,
                    razor_history=razor_h, ember_history=ember_h,
                    judge_feedback=judge_fb, vc_rejection=vc_rejection_feedback
                )
            else:
                console.print(f"  [dim]Max VC attempts ({VC_MAX_REJECTIONS}) reached. Ending session.[/dim]\n")
                break

        else:
            console.print(f"  [dim yellow]...couldn't parse VC decision, treating as CONDITIONAL...[/dim yellow]\n")
            final_decision = "CONDITIONAL"
            if vc_attempt <= VC_MAX_REJECTIONS:
                vc_rejection_feedback = vc_response
                verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
                    premise, transcript,
                    start_round=last_round + 1,
                    num_rounds=EXTRA_ROUNDS_PER_REJECTION,
                    razor_history=razor_h, ember_history=ember_h,
                    judge_feedback=judge_fb, vc_rejection=vc_rejection_feedback
                )
            else:
                break

    # ─── Final pitch ───
    await run_final_pitch(premise, transcript)

    # ─── Save ───
    transcript.append(f"\n{'='*70}")
    transcript.append(f"FINAL VC DECISION: {final_decision}")
    transcript.append(f"TOTAL ROUNDS: {last_round}")
    transcript.append(f"{'='*70}")

    outfile.write_text("\n".join(transcript))

    d_color = "green" if final_decision == "INVEST" else "yellow" if final_decision == "CONDITIONAL" else "red"
    console.print()
    console.print(Panel(
        f"[bold]VC Decision: [{d_color}]{final_decision}[/{d_color}][/bold]\n"
        f"[dim]Total rounds: {last_round} | Transcript saved: {outfile}[/dim]",
        title="SESSION COMPLETE",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    # Check if premise was passed as arg or needs interactive input
    non_flag_args = [a for a in sys.argv[1:] if not a.startswith("--") and
                     (sys.argv.index(a) == 1 or not sys.argv[sys.argv.index(a) - 1].startswith("--"))]

    if non_flag_args:
        premise = non_flag_args[0]
    else:
        console.print()
        console.print("[bold]SPAR[/bold] — paste your premise below. Can be multiple lines.")
        console.print("[dim]Press Enter twice when done.[/dim]\n")
        lines = []
        while True:
            try:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    lines.pop()  # remove trailing blank
                    break
                lines.append(line)
            except EOFError:
                break
        premise = "\n".join(lines).strip()
        if not premise:
            console.print("[red]No premise entered. Exiting.[/red]")
            sys.exit(1)

    asyncio.run(spar(premise))
