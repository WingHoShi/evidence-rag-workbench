# Streaming and operations (controlled evaluation material)

The Campus Planner exposes `updates` for state changes and `messages` for generated token output. The web client displays node progress from `updates` and assistant text from `messages`.

For a custom event, a node emits a small JSON-safe progress object. Do not place a database connection or a Python object in a streamed payload. The production run timeout is 90 seconds; an idle progress signal is emitted every 15 seconds while a long calendar query runs.

The operator dashboard records node name, elapsed milliseconds, outcome, and retry count. It does not record student access tokens or raw authorization headers.
