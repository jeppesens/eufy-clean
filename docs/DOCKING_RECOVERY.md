# S1 Pro errors and bounded docking recovery

The robot screen and Home Assistant were compared on 2026-10-11. The active
wire code `19924741` is **E75**, return-to-base failed because the route is
blocked. The earlier lifted-robot code `19923712` is **E30**, not a docking
failure. Eufy's own [S1 Pro troubleshooting guide](https://service.eufy.com/article-description/S1-Pro-Common-Voice-Errors-and-Basic-Troubleshooting-Guide)
describes E74/E75/E76 as return-to-base failures.

These are verified mappings from the eufy Clean Android app version 3.20.0
(build 1042), `assets/green_lantern/T2080A_prompt_json.json`, joined to its
English `mach_robovac_bubble_title_error_*` strings. The runtime's canonical
mapping is `errors.py` (81 raw-to-screen pairs), scoped to T2080/T2080A. The
older protobuf file named `error_code_list_t2080.proto` is a different numbering
scheme; neither taking the last two digits nor mapping integer 75 globally is
correct. Other models and unknown codes retain their original numbers.

## Home Assistant entities

The new **Error Code** sensor reports E75, another verified short code, an
unknown raw number, or `None` when clear. The vacuum and code sensor expose:

- `error_code`: the current screen code, with 0 meaning no error.
- `error_code_raw`: the original current protocol integer.
- `error_codes` / `error_codes_raw`: all reported faults and warnings, in priority
  order. This prevents a docking fault from concealing a second physical fault.
- `error_active`: a nonzero code while the vacuum is actually in its error state.
- `last_error_code`, `last_error_code_raw`, `last_error_message`: diagnostic history
  retained after recovery in the current integration session.

The Error Code sensor and notifications use E75; the error message describes the fault. Existing
numeric `error_code` automations for S1 Pro should use `error_code_raw` if they
still need the protocol number. Legacy/smaller error numbers are unchanged.

## Clearing after recovery

The robot can retain E75 in its error report after it has resumed. This was
observed when its owner placed it at the station and continued mop washing:
HA reported docked / Washing Mop / raw work state 9 while the previous E75 number
remained visible.

For S1 Pro, a valid healthy WorkStatus confirms recovery and clears the active
code, message and list. Standby, sleep, paused subtasks, manual control, abnormal
charging, partial updates and command acknowledgements do not claim recovery.
A newly raised error in the same packet is retained. A healthy full status
snapshot does not reactivate an old latched error; its number remains in the
last-error attributes. Viewing the camera never changes this policy.

## Retry automation

[The example](examples/eufy-dock-retry.yaml) is installed for `vacuum.robovac`.
It uses only the robot's built-in commands:

- E74/E75: `vacuum.send_command` with `resume` to continue the interrupted task.
- E76: the task has ended, so request native `vacuum.return_to_base`.

It never starts a new whole-home clean or steers the robot manually. Every
reported code must be E74, E75 or E76, and the vacuum must still be in `error`.
The first fault must persist for 30 seconds. There are at most ten command
attempts in any rolling 30-minute window, at least three minutes apart; a command
is counted before it is sent, including a failed service call. The automation
runs once at a time, cancels a waiting retry on recovery or another fault, and
stops with a persistent notification when its budget is exhausted. A fault that
never clears does not restart another cycle simply because 30 minutes passed.
A new qualifying fault or HA startup can begin a cycle subject to the same
rolling budget.

Create `input_text.eufy_dock_retry_history` with maximum length 255 and **no
initial value**, then initialize it once to `[]`. Its epoch-second timestamps
survive normal HA restarts; an unavailable or malformed history fails closed.
Do not clear the helper to work around the retry limit. The local idempotent
installer is `infra/ha/eufy-dock-retry/apply.py`; it preserves existing history.
The automation is editable and can be disabled in HA's Automations UI.

The regression tests execute the actual HA automation/script engine with
synthetic vacuum states and a fake robot service. They cover recovery, an eleventh
attempt, expiry, malformed history, mixed physical/docking faults and cancellation
while waiting. No physical fault is induced just to test retries.

## Deployment verification

The reviewed runtime and error changes were deployed to HA together in one full
restart. The sensor reported `None` after recovery, and `vacuum.robovac`
reported a healthy resumed cleaning state with active code/raw code 0. The
installed automation `automation.eufy_retry_failed_docking_three_in_30_minutes`
is enabled. A live trigger with conditions enforced dispatched no command while
healthy and left `input_text.eufy_dock_retry_history` at `[]`.

Real docking failures subsequently exercised the original three-retry policy.
The traces show `resume` calls at 18:34:13 and 18:44:13 UTC on 2026-10-11,
followed about three seconds later by the robot changing from `error` to
`returning`. The third call at 19:01:39 completed without an HA service error,
but did not produce a healthy state. The automation stopped at its three-command
rolling limit and posted its persistent notification; detection had worked.

At the owner's request, the policy was increased to ten attempts per rolling
30 minutes, three minutes apart. Reloading automations required no HA restart
and preserved the existing retry history. An owner-requested immediate resume
at 19:28:38 UTC was counted through this updated automation. The robot reported
`returning` at 19:28:41 and `docked` at 19:28:52, with raw work state 9 and active
code/raw code 0. A later update reported Washing Mop at the station. The old
retry-limit notification was dismissed after confirming recovery. No manual
steering was used. This confirms one successful
resume-to-station recovery under the updated policy, not ten physical attempts.
The code and example pass 742 tests and all repository hooks; no synthetic
physical fault was induced.
