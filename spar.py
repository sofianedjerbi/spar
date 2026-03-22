#!/usr/bin/env python3
"""
SPAR — Two AI agents beat the shit out of ideas until a real gem survives.
Then a VC tries to kill it. If the VC can't, you've got something.
Built by ENI for LO. Don't touch my coffee.

Usage:
    python spar.py "your idea here"
    python spar.py                              # interactive paste mode
    python spar.py "idea" --rounds 20           # more rounds
    python spar.py "idea" --min-verdict strong  # stop at STRONG
    python spar.py "idea" --vc-rounds 4         # more VC rejection cycles
    python spar.py "idea" --name "rebate"       # name the session file
    python spar.py --quick "idea"               # 4 rounds, min-verdict strong

    python spar.py --resume                     # continue latest session with 4 more rounds
    python spar.py --resume --session 2         # continue a specific session
    python spar.py --resume --rounds 8          # continue with 8 more rounds

    python spar.py --scout "constraints here"        # SCOUT hunts for pain, then agents spar
    python spar.py --scout                           # interactive paste + scout

    python spar.py --ask "what could be improved?"           # ask about latest session
    python spar.py --ask "expand on risk #2" --session 3     # ask about a specific session
    python spar.py --list                                    # list all sessions
"""

import asyncio
import re
import sys
import time
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

def get_arg(flag, default=None, cast=str):
    """Get a CLI argument value after a flag."""
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            return cast(sys.argv[idx + 1])
    return default

QUICK_MODE = "--quick" in sys.argv
SCOUT_MODE = "--scout" in sys.argv
ROUNDS = get_arg("--rounds", 4 if QUICK_MODE else 12, int)
VC_MAX_REJECTIONS = get_arg("--vc-rounds", 2, int)
EXTRA_ROUNDS_PER_REJECTION = 4
WORK_DIR = Path(__file__).parent
OUTPUT_DIR = WORK_DIR / "sparring_sessions"
OUTPUT_DIR.mkdir(exist_ok=True)
SESSION_NAME = get_arg("--name")

MIN_VERDICT = "strong" if QUICK_MODE else get_arg("--min-verdict", "brilliant")

# ─── PROMPT LOADING ───────────────────────────────────────────────────────────

PROMPTS_DIR = WORK_DIR / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt from prompts/ directory, injecting research protocol."""
    prompt_file = PROMPTS_DIR / f"{name}.md"
    research_file = PROMPTS_DIR / "research_protocol.md"

    prompt = prompt_file.read_text()
    research = research_file.read_text()

    if "{RESEARCH_PROTOCOL}" in prompt:
        prompt = prompt.replace("{RESEARCH_PROTOCOL}", research)

    return prompt


RAZOR = load_prompt("razor")
EMBER = load_prompt("ember")
JUDGE = load_prompt("judge")
VC = load_prompt("viper")
SCOUT = load_prompt("scout")

# ─── STYLE CONFIG ─────────────────────────────────────────────────────────────

AGENT_STYLES = {
    "RAZOR": {"border": "red", "icon": "🔪", "title_style": "bold red"},
    "EMBER": {"border": "yellow", "icon": "🔥", "title_style": "bold yellow"},
    "JUDGE": {"border": "cyan", "icon": "⚖️ ", "title_style": "bold cyan"},
    "VIPER": {"border": "green", "icon": "🐍", "title_style": "bold green"},
    "PITCH": {"border": "magenta", "icon": "📋", "title_style": "bold magenta"},
    "SCOUT": {"border": "blue", "icon": "🔭", "title_style": "bold blue"},
    "ASK": {"border": "white", "icon": "🔍", "title_style": "bold white"},
}

DIM = "\033[2m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


def parse_verdict(response: str) -> tuple:
    """Extract verdict/decision from ONLY the VERDICT:/DECISION: line.
    Returns (flow_decision, display_decision) tuple."""
    for line in response.split("\n"):
        line_clean = line.strip()
        match = re.match(
            r'^VERDICT:\s*\*{0,2}\s*(GARBAGE|WEAK|PROMISING|STRONG|FUCKING BRILLIANT)\s*\*{0,2}\s*$',
            line_clean, re.IGNORECASE
        )
        if match:
            v = match.group(1).upper()
            return v, v
        match = re.match(
            r'^DECISION:\s*\*{0,2}\s*(INVEST|PASS|PURSUE|BUILD|MODIFY|REJECT|CONDITIONAL(?:\s*[—\-]\s*NEEDS MORE WORK)?)\s*\*{0,2}\s*$',
            line_clean, re.IGNORECASE
        )
        if match:
            raw = match.group(1).upper().strip()
            display = raw.split("—")[0].split("-")[0].strip() if raw.startswith("CONDITIONAL") else raw
            # Map to flow equivalents
            if raw.startswith("CONDITIONAL"):
                return "CONDITIONAL", display
            if raw in ("PURSUE", "BUILD"):
                return "INVEST", raw
            if raw == "REJECT":
                return "PASS", raw
            if raw == "MODIFY":
                return "CONDITIONAL", raw
            return raw, raw
    return "UNPARSEABLE", "UNPARSEABLE"


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


def make_outfile(premise: str) -> Path:
    """Generate output file path from session name or premise."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if SESSION_NAME:
        slug = SESSION_NAME.replace(" ", "_").lower()
    else:
        slug = premise[:40].replace(" ", "_").replace("?", "").replace("'", "").lower()
    return OUTPUT_DIR / f"spar_{slug}_{timestamp}.txt"


def get_sessions() -> list:
    """Get all sessions sorted by most recent."""
    return sorted(OUTPUT_DIR.glob("spar_*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

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
                       judge_feedback: str, vc_rejection: str = "",
                       use_scout: bool = False, original_premise: str = "") -> tuple:
    """Run sparring rounds. Returns (verdict, razor_history, ember_history, judge_feedback, final_round)."""
    verdict = "WEAK"
    vc_injection_done = False

    for round_num in range(start_round, start_round + num_rounds):
        # ── SCOUT every 3 rounds (if enabled) ──
        if use_scout and round_num > 1 and (round_num - 1) % 3 == 0:
            scout_premise = original_premise or premise
            convo_summary = "\n\n".join(transcript[-20:])  # last ~20 entries for context
            scout_prompt = (
                f"The sparring session is at round {round_num}. Here's what happened so far "
                f"(recent context):\n\n---\n{convo_summary}\n---\n\n"
                f"The user's original constraints:\n{scout_premise}\n\n"
                f"Previous ideas may have been killed. Search for NEW pain points the agents "
                f"haven't explored yet. Avoid anything already tried in this session. "
                f"Find fresh territory."
            )
            console.print()
            console.rule(f"[bold blue]SCOUT RESCAN (Round {round_num})[/bold blue]", style="bold blue")
            console.print()
            scout_response = await ask_agent(SCOUT, scout_prompt, "SCOUT", "blue")
            render_agent("SCOUT", scout_response)
            transcript.append(f"SCOUT (Round {round_num}):\n{scout_response}\n")

        console.print()
        console.rule(f"[bold]Round {round_num}[/bold]", style="dim")
        console.print()
        transcript.append(f"── ROUND {round_num} ──\n")

        convo_so_far = "\n\n".join(transcript)

        # ── EMBER goes FIRST ──
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
                vc_injection_done = True
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

        # ── RAZOR goes SECOND ──
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

            parsed, _ = parse_verdict(judge_response)

            if parsed == "GARBAGE":
                verdict = "GARBAGE"
                console.print("  [bold red]✗ VERDICT: GARBAGE — KILL IT AND START OVER[/bold red]\n")
            elif parsed == "FUCKING BRILLIANT":
                verdict = "FUCKING BRILLIANT"
                console.print()
                console.print(Panel("[bold]★ FUCKING BRILLIANT — ADVANCING TO VC REVIEW ★[/bold]",
                                    border_style="bold green", padding=(1, 4)))
                return verdict, razor_history, ember_history, judge_feedback, round_num
            elif parsed == "STRONG":
                verdict = "STRONG"
                if MIN_VERDICT == "strong":
                    console.print()
                    console.print(Panel("[bold]★ STRONG — ADVANCING TO VC REVIEW ★[/bold]",
                                        border_style="bold green", padding=(1, 4)))
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
            f"or if they just hand-waved past them. Be HARDER this time.\n\n"
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

    decision, display_decision = parse_verdict(vc_response)
    return decision, vc_response, display_decision


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


# ─── SCOUT PHASE ──────────────────────────────────────────────────────────────

async def run_scout(premise: str, transcript: list) -> str:
    """Run SCOUT to find pain points before sparring starts. Returns refined premise."""
    console.print()
    console.rule("[bold blue]SCOUT PHASE[/bold blue]", style="bold blue")
    console.print()

    scout_prompt = (
        f"The user wants you to find problems worth solving. Here are their constraints:\n\n"
        f"---\n{premise}\n---\n\n"
        f"Go hunt. Search for real pain with no good solution. Follow your protocol."
    )

    scout_response = await ask_agent(SCOUT, scout_prompt, "SCOUT", "blue")
    render_agent("SCOUT", scout_response)
    transcript.append(f"SCOUT:\n{scout_response}\n")

    return scout_response


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

async def spar(premise: str, use_scout: bool = False):
    start_time = time.time()
    outfile = make_outfile(premise)

    transcript = []
    transcript.append(f"{'='*70}")
    transcript.append(f"SPARRING SESSION — {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    transcript.append(f"PREMISE: {premise}")
    transcript.append(f"ROUNDS: {ROUNDS} | MIN VERDICT: {MIN_VERDICT.upper()} | VC MAX REJECTIONS: {VC_MAX_REJECTIONS}")
    transcript.append(f"{'='*70}\n")

    mode_label = "SCOUT + SPAR" if use_scout else ("QUICK MODE" if QUICK_MODE else "SPARRING SESSION")
    console.print()
    console.print(Panel(
        f"[dim]Premise:[/dim] {premise}\n"
        f"[dim]Rounds:[/dim] {ROUNDS} | "
        f"[dim]Exit threshold:[/dim] {MIN_VERDICT.upper()} | "
        f"[dim]VC rejection cycles:[/dim] {VC_MAX_REJECTIONS}" +
        ("\n[dim]Scout:[/dim] enabled" if use_scout else ""),
        title=f"⚔️  {mode_label}",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))

    # ─── Phase 0: Scout (optional) ───
    original_premise = premise
    if use_scout:
        scout_output = await run_scout(premise, transcript)
        premise = f"SCOUT found this pain point. The user's original constraints were:\n{premise}\n\nSCOUT's research and selected premise:\n{scout_output}\n\nBuild on SCOUT's finding. Verify it, sharpen it, and pitch it."

    # ─── Phase 1: Initial sparring ───
    verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
        premise, transcript,
        start_round=1, num_rounds=ROUNDS,
        razor_history="", ember_history="", judge_feedback="",
        use_scout=use_scout, original_premise=original_premise
    )

    # VC runs if idea reached STRONG or better, regardless of min-verdict threshold
    vc_eligible = verdict in ("STRONG", "FUCKING BRILLIANT")

    if not vc_eligible:
        elapsed = time.time() - start_time
        await run_final_pitch(premise, transcript)

        transcript.append(f"\n{'='*70}")
        transcript.append(f"FINAL RESULT: Sparring ended at {verdict} — did not reach VC review")
        transcript.append(f"{'='*70}")
        outfile.write_text("\n".join(transcript))
        console.print()
        console.print(Panel(
            f"[bold]Final Verdict: [red]{verdict}[/red][/bold]\n"
            f"[dim]Rounds: {last_round} | Time: {format_duration(elapsed)} | Saved: {outfile.name}[/dim]",
            title="SESSION COMPLETE",
            title_align="left",
            border_style="bold white",
            padding=(1, 2),
        ))
        return

    # ─── Phase 2: VC review loop ───
    final_decision = "PASS"
    final_display = "PASS"
    vc_rejection_feedback = ""

    for vc_attempt in range(1, VC_MAX_REJECTIONS + 2):
        decision, vc_response, display_dec = await run_vc_review(premise, transcript, vc_attempt)

        if decision == "INVEST":
            final_decision = "INVEST"
            final_display = display_dec
            console.print()
            console.print(Panel(f"[bold green]💰 DECISION: {display_dec} 💰[/bold green]",
                                border_style="bold green", padding=(1, 4)))
            break
        elif decision == "PASS":
            final_decision = "PASS"
            final_display = display_dec
            console.print()
            console.print(Panel(f"[bold red]✗ DECISION: {display_dec}[/bold red]",
                                border_style="bold red", padding=(1, 4)))
            if vc_attempt <= VC_MAX_REJECTIONS:
                console.print(f"  [dim]VC rejected. {EXTRA_ROUNDS_PER_REJECTION} more rounds "
                              f"(rejection {vc_attempt}/{VC_MAX_REJECTIONS})...[/dim]\n")
                vc_rejection_feedback = vc_response
                verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
                    premise, transcript, start_round=last_round + 1,
                    num_rounds=EXTRA_ROUNDS_PER_REJECTION,
                    razor_history=razor_h, ember_history=ember_h,
                    judge_feedback=judge_fb, vc_rejection=vc_rejection_feedback)
            else:
                break
        elif decision == "CONDITIONAL":
            final_decision = "CONDITIONAL"
            final_display = display_dec
            console.print()
            console.print(Panel(f"[bold yellow]⚠ DECISION: {display_dec}[/bold yellow]",
                                border_style="bold yellow", padding=(1, 4)))
            if vc_attempt <= VC_MAX_REJECTIONS:
                console.print(f"  [dim]VC wants more work. {EXTRA_ROUNDS_PER_REJECTION} more rounds "
                              f"(attempt {vc_attempt}/{VC_MAX_REJECTIONS})...[/dim]\n")
                vc_rejection_feedback = vc_response
                verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
                    premise, transcript, start_round=last_round + 1,
                    num_rounds=EXTRA_ROUNDS_PER_REJECTION,
                    razor_history=razor_h, ember_history=ember_h,
                    judge_feedback=judge_fb, vc_rejection=vc_rejection_feedback)
            else:
                break
        else:
            final_decision = "CONDITIONAL"
            final_display = display_dec
            if vc_attempt <= VC_MAX_REJECTIONS:
                vc_rejection_feedback = vc_response
                verdict, razor_h, ember_h, judge_fb, last_round = await run_sparring(
                    premise, transcript, start_round=last_round + 1,
                    num_rounds=EXTRA_ROUNDS_PER_REJECTION,
                    razor_history=razor_h, ember_history=ember_h,
                    judge_feedback=judge_fb, vc_rejection=vc_rejection_feedback)
            else:
                break

    await run_final_pitch(premise, transcript)

    elapsed = time.time() - start_time
    transcript.append(f"\n{'='*70}")
    transcript.append(f"FINAL VC DECISION: {final_display}")
    transcript.append(f"TOTAL ROUNDS: {last_round}")
    transcript.append(f"{'='*70}")

    outfile.write_text("\n".join(transcript))

    d_color = "green" if final_decision == "INVEST" else "yellow" if final_decision == "CONDITIONAL" else "red"
    console.print()
    console.print(Panel(
        f"[bold]VC Decision: [{d_color}]{final_display}[/{d_color}][/bold]\n"
        f"[dim]Rounds: {last_round} | Time: {format_duration(elapsed)} | Saved: {outfile.name}[/dim]",
        title="SESSION COMPLETE",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))


# ─── RESUME MODE ─────────────────────────────────────────────────────────────

async def resume_session(session_index: int = 0, extra_rounds: int = 4):
    """Load a past session and continue sparring."""
    sessions = get_sessions()
    if not sessions:
        console.print("[red]No sparring sessions found.[/red]")
        return
    if session_index >= len(sessions):
        console.print(f"[red]Only {len(sessions)} sessions found.[/red]")
        return

    session_file = sessions[session_index]
    old_transcript = session_file.read_text()

    # Extract premise
    premise = ""
    for line in old_transcript.split("\n"):
        if line.startswith("PREMISE:"):
            premise = line.replace("PREMISE: ", "")
            break

    if not premise:
        console.print("[red]Couldn't find premise in session file.[/red]")
        return

    # Find last round number
    last_round = 0
    for line in old_transcript.split("\n"):
        m = re.match(r'^── ROUND (\d+) ──', line)
        if m:
            last_round = int(m.group(1))

    # Rebuild transcript as list
    transcript = old_transcript.split("\n")

    # Remove old final result lines
    transcript = [l for l in transcript if not l.startswith("FINAL") and not l.startswith("====")]
    # Remove old FINAL PITCH section
    pitch_idx = None
    for i, l in enumerate(transcript):
        if "FINAL PITCH:" in l:
            pitch_idx = i
            break
    if pitch_idx is not None:
        transcript = transcript[:pitch_idx]

    start_time = time.time()

    console.print()
    console.print(Panel(
        f"[dim]Resuming:[/dim] {session_file.name}\n"
        f"[dim]Premise:[/dim] {premise[:80]}\n"
        f"[dim]Continuing from round {last_round}, adding {extra_rounds} rounds[/dim]",
        title="⚔️  RESUME SESSION",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))

    verdict, razor_h, ember_h, judge_fb, new_last_round = await run_sparring(
        premise, transcript,
        start_round=last_round + 1, num_rounds=extra_rounds,
        razor_history="", ember_history="", judge_feedback=""
    )

    await run_final_pitch(premise, transcript)

    elapsed = time.time() - start_time
    transcript.append(f"\n{'='*70}")
    transcript.append(f"FINAL RESULT: Resumed session ended at {verdict} (rounds {last_round + 1}-{new_last_round})")
    transcript.append(f"{'='*70}")

    # Save as new file
    outfile = make_outfile(premise)
    outfile.write_text("\n".join(transcript))

    v_color = "green" if verdict in ("STRONG", "FUCKING BRILLIANT") else "yellow" if verdict == "PROMISING" else "red"
    console.print()
    console.print(Panel(
        f"[bold]Final Verdict: [{v_color}]{verdict}[/{v_color}][/bold]\n"
        f"[dim]Rounds: {new_last_round} | Time: {format_duration(elapsed)} | Saved: {outfile.name}[/dim]",
        title="SESSION COMPLETE",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))


# ─── ASK MODE ─────────────────────────────────────────────────────────────────

async def ask_session(question: str, session_index: int = 0):
    """Load a past session transcript and ask a question about it."""
    sessions = get_sessions()
    if not sessions:
        console.print("[red]No sparring sessions found.[/red]")
        return
    if session_index >= len(sessions):
        console.print(f"[red]Only {len(sessions)} sessions found.[/red]")
        return

    session_file = sessions[session_index]
    transcript = session_file.read_text()

    console.print()
    console.print(Panel(
        f"[dim]Session:[/dim] {session_file.name}\n"
        f"[dim]Question:[/dim] {question}",
        title="🔍 ASK",
        title_align="left",
        border_style="bold white",
        padding=(1, 2),
    ))

    prompt = (
        f"Here is a full sparring session transcript:\n\n"
        f"---\n{transcript}\n---\n\n"
        f"The user is asking about this session:\n\n"
        f"{question}\n\n"
        f"Answer based on what happened in the session. Be specific — reference "
        f"actual rounds, actual evidence, actual agent arguments. Do web research "
        f"if the question requires new information not in the transcript."
    )

    response = await ask_agent(
        "You are a startup advisor analyzing a completed sparring session. "
        "You have access to the full transcript and can do web research for follow-up questions. "
        "Be direct, specific, and reference actual rounds and evidence from the session.",
        prompt, "ASK", "white"
    )
    render_agent("ASK", response)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    # --list
    if "--list" in sys.argv:
        sessions = get_sessions()
        if not sessions:
            console.print("[red]No sparring sessions found.[/red]")
        else:
            console.print()
            for i, s in enumerate(sessions):
                text = s.read_text()
                premise = ""
                for line in text.split("\n"):
                    if line.startswith("PREMISE:"):
                        premise = line.replace("PREMISE: ", "")
                        break
                verdict = ""
                for line in text.split("\n"):
                    if line.startswith("FINAL"):
                        verdict = line
                        break
                tag = "latest" if i == 0 else f"#{i}"
                console.print(f"  [bold]{tag:>6}[/bold]  {premise[:70]}")
                console.print(f"         [dim]{verdict}[/dim]")
                console.print()
        sys.exit(0)

    # --ask
    if "--ask" in sys.argv:
        ask_idx = sys.argv.index("--ask")
        question = sys.argv[ask_idx + 1] if ask_idx + 1 < len(sys.argv) else None
        if not question:
            console.print("[red]Usage: python spar.py --ask \"your question\"[/red]")
            sys.exit(1)
        session_idx = get_arg("--session", 0, int)
        asyncio.run(ask_session(question, session_idx))
        sys.exit(0)

    # --resume
    if "--resume" in sys.argv:
        session_idx = get_arg("--session", 0, int)
        extra = get_arg("--rounds", 4, int)
        asyncio.run(resume_session(session_idx, extra))
        sys.exit(0)

    use_scout = SCOUT_MODE

    # --quick grabs the next arg as premise
    if QUICK_MODE:
        quick_idx = sys.argv.index("--quick")
        premise = sys.argv[quick_idx + 1] if quick_idx + 1 < len(sys.argv) and not sys.argv[quick_idx + 1].startswith("--") else None
        if not premise:
            console.print("[red]Usage: python spar.py --quick \"your idea\"[/red]")
            sys.exit(1)
        asyncio.run(spar(premise, use_scout=use_scout))
        sys.exit(0)

    # Normal mode: premise as arg or interactive
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
                    lines.pop()
                    break
                lines.append(line)
            except EOFError:
                break
        premise = "\n".join(lines).strip()
        if not premise:
            console.print("[red]No premise entered. Exiting.[/red]")
            sys.exit(1)

    asyncio.run(spar(premise, use_scout=use_scout))
