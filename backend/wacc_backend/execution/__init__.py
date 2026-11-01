"""Windows Execution Backend (T-0009). Follows docs/EXECUTION_SECURITY.md.

Every machine action goes through ExecutionService: classify -> policy -> (approval) -> executor -> audit.
"""
