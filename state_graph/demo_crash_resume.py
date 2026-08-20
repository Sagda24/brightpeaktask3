"""
Proof that checkpointing survives an actual process kill, not just a
pause-and-resume inside the same running process.

Usage:
    python -m state_graph.demo_crash_resume start
        -> runs graph_1 (probation monitoring) through INTAKE, then
           BUILD_INTERVENTION_PLAN deliberately calls os._exit(137) mid-node,
           simulating `kill -9` on the process. Prints the run_id.

    python -m state_graph.demo_crash_resume resume <run_id>
        -> a FRESH python process loads only the run_id, reads the last
           checkpoint from disk, and continues. INTAKE is not re-run (its
           checkpoint already shows FETCH_POLICY/BUILD_INTERVENTION_PLAN's
           predecessor state); only the step that was interrupted resumes.

    python -m state_graph.demo_crash_resume history <run_id>
        -> prints every checkpoint row for the run, so you can see there was
           no gap and no lost context across the kill.
"""

import json
import sys

from state_graph.graph_1.graph import build_graph
from state_graph.checkpointing.store import CheckpointStore


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    graph = build_graph()

    if cmd == "start":
        import os
        os.environ["SIMULATE_CRASH"] = "1"
        context = {
            "student_id": 1,
            "term": "Fall2026",
            "_force_flag_for_demo": True,  # student_id=1's real average is above
                                            # the threshold; force the probation
                                            # path so the demo actually reaches
                                            # BUILD_INTERVENTION_PLAN
        }
        run_id = graph.start(context)
        # If we get here, the simulated crash didn't fire (e.g. student_id=1
        # wasn't actually below the probation threshold) -- print run_id
        # regardless so the demo is inspectable either way.
        print(f"run_id={run_id}")

    elif cmd == "resume":
        run_id = sys.argv[2]
        graph.resume(run_id)
        print(f"resumed run_id={run_id} to completion (or its next pause)")

    elif cmd == "history":
        run_id = sys.argv[2]
        for row in CheckpointStore().history(run_id):
            print(f"seq={row['seq']:>3}  state={row['state']:<28}  status={row['status']:<10}  "
                  f"terms_monitored={row['context'].get('terms_monitored')}")


if __name__ == "__main__":
    main()
