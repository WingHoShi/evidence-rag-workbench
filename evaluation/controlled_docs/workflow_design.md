# Workflow design (controlled evaluation material)

The Campus Planner graph has three nodes: `intake`, `schedule`, and `review`. Nodes receive the current state and return partial state updates. The fixed edge is `intake -> schedule`.

The `schedule` node conditionally routes to `review` only when the student requests a manual check; otherwise it routes to `END`. The shared state keeps raw fields such as course names and deadlines. Prompt-formatted text is derived when a node needs it and is not persisted in state.

The schedule node calls a calendar tool. Transient HTTP 5xx failures use a retry policy with at most three attempts. A missing course name is user-fixable and should pause for clarification rather than retry automatically.
