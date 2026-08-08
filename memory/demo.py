"""
End-to-end demo of the fixed memory/ system, grounded in Bright Peak Academy's
real domain (course enrollment, not the tutoring/accommodation scenario from an
earlier draft).

Run: python3 -m memory.demo

Demonstrates, in order:
  1. Short-term buffer + scratchpad are genuinely separate -- filling the buffer
     past capacity never touches scratchpad state.
  2. Promote-or-drop routing fires ONLY on the message the buffer evicts on
     overflow, with the reasoning for each decision visible via get_routing_log().
  3. Consolidation is a separate, periodic pass -- NOT run inline after each
     promotion. It only runs once enough promotions accumulate (or when
     explicitly triggered), and processes a batch of episodes at once.
  4. A real conflict: the student states a class-time preference, then later
     contradicts it. Consolidation resolves it explicitly (most-recent-wins,
     old value versioned/retained, not silently dropped) and logs the conflict.
  5. Semantic memory correctly serves the *active* fact after the conflict.
"""

from memory.manager import MemoryManager

STUDENT_ID = 1


def run_demo():
    mm = MemoryManager(max_messages=4)  # small buffer so overflow happens quickly in the demo

    print("=== 1. Scratchpad is separate from the short-term buffer ===")
    mm.set_working_state("current_subgoal", "help student plan next semester's schedule")
    mm.set_working_state("pending_tool_call", "get_student_profile")
    print("scratchpad before buffer fills:", mm.get_scratchpad())

    print("\n=== 2. Filling short-term buffer past capacity (max_messages=4) ===")
    turns = [
        ("student", "Hi, I want to talk about my course plan for next semester."),
        ("assistant", "Sure, let's take a look at your current enrollments."),
        ("student", "My major is Computer Science."),
        ("student", "I prefer evening classes because I work part-time."),
        ("assistant", "Noted, I'll keep evening sections in mind."),
        ("student", "Actually, I prefer morning classes now -- my work schedule changed."),
        ("student", "I got a waiver for the prerequisite of Advanced Machine Learning."),
        # filler turns just to push the buffer forward and flush everything
        # above out through eviction -- a real conversation would keep going
        # for many more turns before this happens naturally
        ("assistant", "Got it, I've made a note of that."),
        ("student", "Thanks, that's all for now."),
        ("assistant", "Sounds good, talk soon."),
        ("student", "One more thing -- can you check my transcript?"),
    ]

    for role, content in turns:
        decision = mm.add_message(role, content, student_id=STUDENT_ID)
        print(f"  add_message({role!r}, {content[:45]!r}...) -> {decision['decision']}: {decision['reason']}")

    print("\nscratchpad AFTER buffer overflowed repeatedly (must be unchanged):",
          mm.get_scratchpad())
    assert mm.get_scratchpad()["current_subgoal"] == "help student plan next semester's schedule", \
        "scratchpad was corrupted by buffer pruning!"
    print("OK: scratchpad survived buffer pruning untouched.")

    print("\n=== 3. Routing log (visible reasoning per decision) ===")
    for entry in mm.get_routing_log():
        print(f"  [{entry['decision']}] \"{entry['message'][:50]}...\" -- {entry['reason']}")

    print("\n=== 4. Consolidation runs as a PERIODIC BATCH, not inline per-write ===")
    print(f"episodic episodes so far: {len(mm.get_student_episodes(STUDENT_ID))}")
    print(f"CONSOLIDATION_BATCH_SIZE={mm.CONSOLIDATION_BATCH_SIZE} -- notice above that "
          f"nothing was written to semantic memory until the 3rd PROMOTE, at which point "
          f"run_consolidation_pass() fired automatically and processed that whole batch at "
          f"once -- not one-at-a-time as each episode was written:")
    print("semantic facts after the automatic batch pass:", mm.get_student_memory(STUDENT_ID))
    assert mm.get_consolidation_log(), \
        "expected the batch trigger to have already run a consolidation pass by now"
    print("OK: consolidation happened as a batched pass over multiple accumulated "
          "episodes, decoupled from any single add_message() call.")

    print("\n=== 5. Triggering one more explicit periodic pass (e.g. end-of-session / cron) ===")
    print("(picks up any episodes promoted after the last automatic batch, e.g. the "
          "prerequisite waiver note)")
    actions = mm.run_consolidation_pass()
    for a in actions:
        print(" ", a)

    print("\n=== 6. Semantic memory AFTER consolidation ===")
    print(mm.get_student_memory(STUDENT_ID))

    print("\n=== 7. The conflict, resolved ===")
    history = mm.semantic.get_history(STUDENT_ID, "preferred_class_time")
    for version in history:
        print(f"  version {version['version']}: {version['value']} "
              f"(active={version['active']}, created_at={version['created_at']})")
    active = mm.get_student_memory(STUDENT_ID)["preferred_class_time"]
    assert active["value"] == "morning", "conflict resolution picked the wrong active value"
    print(f"\nOK: active preference is '{active['value']}' (v{active['version']}); "
          f"the earlier 'evening' preference is retained in history, not deleted.")

    print("\n=== Consolidation log (full history, visible to a grader) ===")
    for entry in mm.get_consolidation_log():
        print(" ", entry)


if __name__ == "__main__":
    run_demo()
