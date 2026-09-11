# Checkpoint guide (controlled evaluation material)

This original document defines a fictional Campus Planner workflow. A checkpoint is a saved workflow state associated with one `thread_id`. The planner writes a checkpoint after the intake node and after the schedule node.

If a schedule node crashes, the planner resumes from the last completed checkpoint rather than rerunning the intake node. A checkpoint belongs to one thread and is not a cross-user profile.

The `student_profile` store is long-term information shared across a student's separate threads. Checkpoints are short-term thread state; the store is cross-thread memory.
