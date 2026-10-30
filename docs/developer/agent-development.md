# Agent Development Guide

How to create, customize, and extend agents in the Multi-Agent Workflow System.

## Agent Architecture

Each agent is an autonomous LLM-driven process that:
1. Receives a task with context
2. Plans and executes work using tools
3. Reports progress via heartbeats
4. Completes with structured handoff

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Process                           │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Profile   │  │   Skills    │  │      Tools          │  │
│  │  (model,    │  │  (procedural│  │  (kanban, terminal, │  │
│  │   prompt,   │  │   knowledge)│  │   web, code, etc.)  │  │
│  │   tools)    │  │             │  │                     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                    │              │
│         └────────────────┼────────────────────┘              │
│                          ▼                                   │
│              ┌─────────────────────┐                          │
│              │    Agent Loop       │                          │
│              │  (plan → act → obs) │                          │
│              └──────────┬──────────┘                          │
│                         │                                      │
│              ┌──────────┴──────────┐                          │
│              ▼                     ▼                          │
│       ┌─────────────┐       ┌─────────────┐                  │
│       │   Kanban    │       │  Workspace  │                  │
│       │   Updates   │       │  (files,    │                  │
│       │ (heartbeat, │       │   git,      │                  │
│       │  progress)  │       │   artifacts)│                  │
│       └─────────────┘       └─────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

## Creating a Custom Agent Profile

### 1. Define Profile YAML

Create `config/profiles/my-agent.yaml`:

```yaml
name: my-agent
extends: base-developer  # Optional: inherit from base
model:
  provider: openrouter
  name: anthropic/claude-3.5-sonnet
  temperature: 0.3
  max_tokens: 16384
tools:
  - kanban
  - terminal
  - read_file
  - write_file
  - patch
  - search_files
  - execute_code
  - web_search
  - web_extract
  - skill_view
  - skill_manage
skills:
  - python
  - test-driven-development
  - my-custom-skill
prompt: |
  You are MY-AGENT, a specialized agent for [domain].
  
  ## Mission
  [Describe the agent's purpose and scope]
  
  ## Operating Principles
  - [Principle 1]
  - [Principle 2]
  
  ## Tool Usage
  - Use `terminal` for running commands
  - Use `write_file` for creating files
  - Use `patch` for targeted edits
  - Always verify with tests before completing
  
  ## Completion Criteria
  - [Criterion 1]
  - [Criterion 2]
  
  ## Output Format
  Return ONLY valid JSON matching the completion contract.
env:
  CUSTOM_VAR: value
```

### 2. Register Profile

The dispatcher auto-discovers profiles in `config/profiles/*.yaml`. No restart needed for new profiles.

### 3. Test the Agent

```bash
# Create a test task
hermes-kanban create \
  --title "Test my-agent" \
  --assignee my-agent \
  --body "Say hello and list files in workspace"
```

---

## Building Custom Skills

Skills are reusable procedural knowledge packages.

### Skill Structure

```
my-skill/
├── SKILL.md              # Main definition (required)
├── references/
│   └── api.md           # Reference documentation
├── templates/
│   └── component.tsx    # Code templates
├── scripts/
│   └── validate.py      # Helper scripts
└── assets/
    └── schema.json      # Static assets
```

### SKILL.md Format

```markdown
---
name: my-skill
description: Use when [trigger]. [One-line behavior].
category: development
version: 1.0.0
tags: [python, testing, api]
---

# My Skill

Use when you need to [specific scenario]. This skill provides [what it does].

## When to Use

- [Scenario 1]
- [Scenario 2]

## Procedures

### Procedure 1: [Name]

**Trigger:** [When to apply]

**Steps:**
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Verification:**
- [Check 1]
- [Check 2]

**Common Pitfalls:**
- [Pitfall 1] → [Solution]
- [Pitfall 2] → [Solution]

## Reference

See `references/api.md` for detailed API documentation.

## Templates

Use `templates/component.tsx` as starting point.
```

### Creating a Skill

```bash
# Via CLI
hermes-kanban skill create --name my-skill --category development

# Or manually create directory structure
mkdir -p config/skills/my-skill/{references,templates,scripts,assets}
```

### Loading Skills

**In Profile (auto-loaded):**
```yaml
skills:
  - my-skill
```

**At Runtime (ad-hoc):**
```bash
hermes-kanban create --title "Task" --assignee sdlc-developer --skills my-skill
```

**In Agent (dynamic):**
```python
# Agent can call skill_view to load skill
skill_view(name="my-skill")
```

---

## Tool Development

### Built-in Toolsets

| Toolset | Tools | Use Case |
|---------|-------|----------|
| `kanban` | create, show, list, complete, ... | Task management |
| `terminal` | command execution | Running scripts, builds |
| `files` | read_file, write_file, patch, search_files | File operations |
| `web` | web_search, web_extract | Research |
| `code` | execute_code | Python execution |
| `skills` | skill_view, skill_manage | Skill management |
| `browser` | browser_exec | Web automation |

### Creating Custom Tools

Tools are Python functions exposed via the tool registry.

#### 1. Define Tool Schema

```python
# tools/my_tool.py
from pydantic import BaseModel, Field
from hermes_tools import tool

class MyToolInput(BaseModel):
    param1: str = Field(description="Description")
    param2: int = Field(default=10, description="Optional param")

class MyToolOutput(BaseModel):
    result: str
    success: bool

@tool(
    name="my_tool",
    description="Description of what this tool does",
    input_schema=MyToolInput,
    output_schema=MyToolOutput
)
async def my_tool(input: MyToolInput) -> MyToolOutput:
    # Implementation
    result = do_something(input.param1, input.param2)
    return MyToolOutput(result=result, success=True)
```

#### 2. Register Tool

```python
# tools/__init__.py
from .my_tool import my_tool

TOOL_REGISTRY = {
    "my_tool": my_tool,
    # ...
}
```

#### 3. Add to Profile

```yaml
tools:
  - kanban
  - terminal
  - my_tool  # Custom tool
```

---

## Agent Loop Customization

### Default Loop (`services/agent-management/agent_loop.py`)

```python
async def agent_loop(
    task: Task,
    profile: Profile,
    skills: List[Skill],
    tools: ToolRegistry,
    workspace: Workspace
) -> AgentResult:
    # 1. Initialize context
    context = build_context(task, profile, skills)
    
    # 2. Main loop
    for turn in range(max_turns):
        # 3. LLM inference
        response = await llm_complete(
            messages=context.messages,
            tools=tools.get_schemas(),
            model=profile.model
        )
        
        # 4. Handle tool calls
        if response.tool_calls:
            for call in response.tool_calls:
                result = await tools.execute(call.name, call.arguments)
                context.add_tool_result(call.id, result)
                
                # Heartbeat
                await kanban.heartbeat(task.id, note=f"Executed {call.name}")
        
        # 5. Check for completion
        if response.is_final:
            return AgentResult(
                success=True,
                output=response.content,
                metadata=context.metadata
            )
    
    # Max turns reached
    return AgentResult(success=False, error="Max turns exceeded")
```

### Custom Loop Hooks

Extend via profile `loop_hooks`:

```yaml
loop_hooks:
  pre_turn: "hooks.my_hooks.pre_turn"
  post_turn: "hooks.my_hooks.post_turn"
  pre_tool: "hooks.my_hooks.pre_tool"
  post_tool: "hooks.my_hooks.post_tool"
  on_error: "hooks.my_hooks.on_error"
```

```python
# hooks/my_hooks.py
async def pre_turn(context: AgentContext, turn: int):
    # Inject context, check budget
    pass

async def post_tool(context: AgentContext, tool_name: str, result: ToolResult):
    # Log, validate, checkpoint
    if tool_name == "write_file":
        await validate_syntax(result.path)
```

---

## Workspace Management

### Workspace Types

| Type | Use Case | Persistence |
|------|----------|-------------|
| `scratch` | Default, isolated temp dir | Cleaned on completion |
| `dir` | Shared persistent directory | Survives task completion |
| `worktree` | Git worktree with branch | Git history preserved |

### Workspace API

```python
# In agent code (via terminal tool)
workspace = get_workspace()  # Injected by runtime

# Read file
content = workspace.read_file("src/main.py")

# Write file
workspace.write_file("src/new.py", "print('hello')")

# Run command
result = workspace.run_command("pytest -v")

# Git operations
workspace.git_commit("feat: add feature")
workspace.git_push()
```

### Scoped Filesystem (ADR-017)

Agents **cannot** access files outside their workspace:

```python
# This FAILS - outside workspace
read_file("/etc/passwd")

# This WORKS - inside workspace
read_file("src/config.py")

# Workspace root varies by type:
# scratch: /tmp/hermes-workspaces/task-{id}/
# dir: /configured/path/
# worktree: /repo/.worktrees/task-{id}/
```

---

## Communication Patterns

### Parent → Child (via metadata)

```json
// Parent completes with metadata
{
  "summary": "Done",
  "metadata": {
    "api_spec": {"endpoints": [...], "schemas": {...}},
    "database_schema": "sql...",
    "key_decisions": ["Use JWT", "PostgreSQL"]
  }
}
```

```python
# Child reads parent metadata
parent_metadata = task.get_parent_metadata()
api_spec = parent_metadata.get("api_spec")
```

### Agent → Kanban (Heartbeats)

```python
# Periodic progress updates
await kanban.heartbeat(
    task_id="t_123",
    note="Implemented user model, writing tests..."
)

# Structured progress
await kanban.heartbeat(
    task_id="t_123",
    note="",
    metadata={"progress": 0.6, "phase": "testing"}
)
```

### Agent → Human (Review)

```python
# Request review with artifacts
await kanban.request_review(
    task_id="t_123",
    summary="Ready for review",
    reviewer="sdlc-reviewer",
    artifacts=["/workspace/src/auth.py"]
)
```

---

## Testing Agents

### Unit Testing Agent Logic

```python
# tests/test_my_agent.py
import pytest
from agent_loop import agent_loop
from test_fixtures import mock_task, mock_profile, mock_workspace

@pytest.mark.asyncio
async def test_agent_completes_simple_task():
    task = mock_task(title="Create hello.py", assignee="my-agent")
    profile = mock_profile(name="my-agent")
    workspace = mock_workspace()
    
    result = await agent_loop(task, profile, [], {}, workspace)
    
    assert result.success
    assert "hello.py" in workspace.list_files()
    content = workspace.read_file("hello.py")
    assert "print" in content
```

### Integration Testing

```python
# tests/integration/test_agent_pipeline.py
@pytest.mark.asyncio
async def test_full_pipeline(dispatcher, kanban_db):
    # Create task via API
    task = await api.create_task({
        "title": "Test feature",
        "assignee": "sdlc-developer"
    })
    
    # Wait for completion
    result = await wait_for_completion(task.id, timeout=120)
    
    assert result.status == "done"
    assert result.metadata["tests_run"] > 0
```

### Mocking LLMs for Tests

```python
# conftest.py
@pytest.fixture
def mock_llm(monkeypatch):
    async def mock_complete(messages, tools, model):
        return MockResponse(
            content='{"tool": "write_file", "args": {"path": "test.py", "content": "pass"}}',
            tool_calls=[MockToolCall(name="write_file", arguments={"path": "test.py", "content": "pass"})]
        )
    
    monkeypatch.setattr("llm.complete", mock_complete)
```

---

## Best Practices

### 1. Keep Prompts Focused
- One clear mission per agent
- Explicit completion criteria
- Concrete tool usage guidance

### 2. Validate Early
```python
# In agent code
def validate_output(output: str) -> bool:
    try:
        json.loads(output)
        return True
    except json.JSONDecodeError:
        return False
```

### 3. Handle Errors Gracefully
```python
try:
    result = await tool.execute(...)
except ToolError as e:
    # Log, retry, or escalate
    await kanban.block(task.id, reason=f"Tool failed: {e}", kind="capability")
    return
```

### 4. Checkpoint Long Tasks
```python
# Save progress every N turns
if turn % 5 == 0:
    await kanban.heartbeat(task.id, metadata={
        "checkpoint": True,
        "files_changed": workspace.get_changed_files()
    })
```

### 5. Use Structured Outputs
```python
# Define output schema
class CompletionOutput(BaseModel):
    changed_files: List[str]
    tests_run: int
    coverage: float
    summary: str

# In prompt: "Return ONLY valid JSON matching CompletionOutput schema"
```

---

## Debugging Agents

### Enable Verbose Logging
```bash
# In profile
env:
  AGENT_LOG_LEVEL: DEBUG
  AGENT_LOG_TOOL_CALLS: "true"
```

### Inspect Conversation History
```python
# In agent loop hook
async def post_turn(context, turn):
    print(f"Turn {turn}: {len(context.messages)} messages")
    for msg in context.messages[-3:]:
        print(f"  {msg.role}: {msg.content[:100]}...")
```

### Replay Failed Tasks
```bash
# Re-run with same task ID (idempotency)
hermes-kanban create --title "Retry" --assignee my-agent \
  --idempotency-key "original-task-key"
```

---

*See also: [API Reference](api-reference.md) | [Kanban Integration](kanban-integration.md) | [Quality Gates](quality-gates.md) | [Architecture Decisions](architecture-decisions/adr-index.md)*