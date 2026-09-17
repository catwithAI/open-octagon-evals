"""Agent-as-a-Judge service: a tool-using pi agent scores a dimension by
inspecting evidence files in a workspace.

The eval core calls this service over HTTP (see ``scorers.agent_judge_client``);
it is deliberately a separate process boundary so the pi subprocess, temp
workspaces and model credentials are isolated from the eval API.
"""
