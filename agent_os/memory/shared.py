"""
Shared memory pool for multi-agent workflows.

Provides thread-safe shared state for agents working together
in workflows. Supports broadcasting, state sharing, and
workflow-scoped context.
"""

import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class SharedMessage:
    """A message broadcast to the shared pool."""
    id: str
    from_agent: str
    content: Any
    timestamp: datetime = field(default_factory=datetime.now)
    recipients: Set[str] = field(default_factory=set)  # Empty = broadcast to all


@dataclass
class AgentOutput:
    """Output from an agent stored in the pool."""
    agent: str
    output: Any
    phase: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SharedMemoryPool:
    """
    Thread-safe shared memory for multi-agent workflows.

    Provides:
    - Key-value state sharing between agents
    - Agent output history tracking
    - Message broadcasting
    - Workflow phase tracking
    - Singleton pattern per workflow

    Example:
        # Get shared pool for a workflow
        pool = SharedMemoryPool.get_pool("deployment_workflow")

        # Agent A sets state
        pool.set("analysis_result", result_data, agent="AnalysisAgent")

        # Agent B reads state
        analysis = pool.get("analysis_result")

        # Broadcast to all agents
        pool.broadcast("Analysis complete, proceeding to deployment", "AnalysisAgent")
    """

    # Class-level registry of pools (singleton per workflow)
    _instances: Dict[str, "SharedMemoryPool"] = {}
    _global_lock = threading.Lock()

    @classmethod
    def get_pool(cls, workflow_id: str) -> "SharedMemoryPool":
        """
        Get or create shared pool for a workflow.

        Thread-safe singleton pattern ensures one pool per workflow.

        Args:
            workflow_id: Unique identifier for the workflow

        Returns:
            SharedMemoryPool instance for the workflow
        """
        with cls._global_lock:
            if workflow_id not in cls._instances:
                cls._instances[workflow_id] = SharedMemoryPool(workflow_id)
            return cls._instances[workflow_id]

    @classmethod
    def destroy_pool(cls, workflow_id: str) -> bool:
        """
        Destroy a workflow's shared pool.

        Call this when a workflow completes to free resources.

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if pool was destroyed, False if not found
        """
        with cls._global_lock:
            if workflow_id in cls._instances:
                del cls._instances[workflow_id]
                return True
            return False

    @classmethod
    def list_pools(cls) -> List[str]:
        """List all active workflow pool IDs."""
        with cls._global_lock:
            return list(cls._instances.keys())

    def __init__(self, workflow_id: str):
        """
        Initialize shared memory pool.

        Note: Use get_pool() instead of direct instantiation
        to ensure singleton behavior.

        Args:
            workflow_id: Unique workflow identifier
        """
        self.workflow_id = workflow_id
        self._lock = threading.RLock()  # Reentrant lock for nested calls

        # Core state storage
        self._state: Dict[str, Any] = {}
        self._state_metadata: Dict[str, Dict[str, Any]] = {}

        # Agent tracking
        self._agent_outputs: Dict[str, List[AgentOutput]] = defaultdict(list)
        self._registered_agents: Set[str] = set()

        # Message queue
        self._messages: List[SharedMessage] = []
        self._message_counter = 0

        # Workflow tracking
        self._current_phase: str = ""
        self._phase_history: List[Dict[str, Any]] = []
        self._created_at = datetime.now()

    def set(
        self,
        key: str,
        value: Any,
        agent: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Set a shared state value.

        Args:
            key: State key
            value: Value to store
            agent: Agent setting the value
            metadata: Optional metadata
        """
        with self._lock:
            self._state[key] = value
            self._state_metadata[key] = {
                "set_by": agent,
                "set_at": datetime.now().isoformat(),
                "metadata": metadata or {}
            }
            self._registered_agents.add(agent)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a shared state value.

        Args:
            key: State key
            default: Default if key not found

        Returns:
            Stored value or default
        """
        with self._lock:
            return self._state.get(key, default)

    def get_with_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get value with its metadata.

        Args:
            key: State key

        Returns:
            Dict with 'value' and 'metadata', or None if not found
        """
        with self._lock:
            if key not in self._state:
                return None
            return {
                "value": self._state[key],
                **self._state_metadata.get(key, {})
            }

    def delete(self, key: str) -> bool:
        """
        Delete a state key.

        Args:
            key: Key to delete

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if key in self._state:
                del self._state[key]
                self._state_metadata.pop(key, None)
                return True
            return False

    def keys(self) -> List[str]:
        """Get all state keys."""
        with self._lock:
            return list(self._state.keys())

    def has(self, key: str) -> bool:
        """Check if key exists."""
        with self._lock:
            return key in self._state

    def record_output(
        self,
        agent: str,
        output: Any,
        phase: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record an agent's output.

        Maintains history of what each agent has produced.

        Args:
            agent: Agent name
            output: Output content
            phase: Workflow phase (uses current if not specified)
            metadata: Optional metadata
        """
        with self._lock:
            record = AgentOutput(
                agent=agent,
                output=output,
                phase=phase or self._current_phase,
                metadata=metadata or {}
            )
            self._agent_outputs[agent].append(record)
            self._registered_agents.add(agent)

    def get_agent_outputs(
        self,
        agent: str,
        limit: Optional[int] = None
    ) -> List[AgentOutput]:
        """
        Get outputs from a specific agent.

        Args:
            agent: Agent name
            limit: Max outputs to return (None = all)

        Returns:
            List of AgentOutput records
        """
        with self._lock:
            outputs = self._agent_outputs.get(agent, [])
            if limit:
                return outputs[-limit:]
            return list(outputs)

    def get_last_output(self, agent: str) -> Optional[Any]:
        """
        Get the most recent output from an agent.

        Args:
            agent: Agent name

        Returns:
            Last output value, or None
        """
        with self._lock:
            outputs = self._agent_outputs.get(agent, [])
            if outputs:
                return outputs[-1].output
            return None

    def get_all_outputs(self) -> Dict[str, List[AgentOutput]]:
        """Get all outputs from all agents."""
        with self._lock:
            return dict(self._agent_outputs)

    def broadcast(
        self,
        content: Any,
        from_agent: str,
        recipients: Optional[Set[str]] = None
    ) -> str:
        """
        Broadcast a message to agents.

        Args:
            content: Message content
            from_agent: Sending agent
            recipients: Specific recipients (None = all agents)

        Returns:
            Message ID
        """
        with self._lock:
            self._message_counter += 1
            msg_id = f"msg_{self.workflow_id}_{self._message_counter}"

            message = SharedMessage(
                id=msg_id,
                from_agent=from_agent,
                content=content,
                recipients=recipients or set()
            )
            self._messages.append(message)
            self._registered_agents.add(from_agent)

            return msg_id

    def get_messages(
        self,
        for_agent: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[SharedMessage]:
        """
        Get messages from the pool.

        Args:
            for_agent: Filter to messages for this agent (None = all)
            since: Only messages after this time
            limit: Max messages to return

        Returns:
            List of SharedMessage objects
        """
        with self._lock:
            messages = self._messages

            # Filter by recipient
            if for_agent:
                messages = [
                    m for m in messages
                    if not m.recipients or for_agent in m.recipients
                ]

            # Filter by time
            if since:
                messages = [m for m in messages if m.timestamp > since]

            # Apply limit
            if limit:
                messages = messages[-limit:]

            return list(messages)

    def set_phase(self, phase: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Set current workflow phase.

        Args:
            phase: Phase name
            metadata: Optional phase metadata
        """
        with self._lock:
            # Record previous phase
            if self._current_phase:
                self._phase_history.append({
                    "phase": self._current_phase,
                    "ended_at": datetime.now().isoformat()
                })

            self._current_phase = phase

    def get_phase(self) -> str:
        """Get current workflow phase."""
        with self._lock:
            return self._current_phase

    def get_phase_history(self) -> List[Dict[str, Any]]:
        """Get history of workflow phases."""
        with self._lock:
            return list(self._phase_history)

    def get_workflow_context(self) -> Dict[str, Any]:
        """
        Get complete workflow context.

        Useful for injecting into agent prompts.

        Returns:
            Dict with state, outputs, messages, and phase info
        """
        with self._lock:
            return {
                "workflow_id": self.workflow_id,
                "current_phase": self._current_phase,
                "state": dict(self._state),
                "registered_agents": list(self._registered_agents),
                "agent_output_counts": {
                    agent: len(outputs)
                    for agent, outputs in self._agent_outputs.items()
                },
                "message_count": len(self._messages),
                "created_at": self._created_at.isoformat()
            }

    def get_context_for_agent(self, agent: str) -> Dict[str, Any]:
        """
        Get context relevant to a specific agent.

        Includes shared state, recent messages, and outputs
        from other agents.

        Args:
            agent: Agent name

        Returns:
            Context dict for the agent
        """
        with self._lock:
            # Get recent messages for this agent
            recent_messages = self.get_messages(for_agent=agent, limit=10)

            # Get last outputs from other agents
            other_outputs = {}
            for other_agent, outputs in self._agent_outputs.items():
                if other_agent != agent and outputs:
                    other_outputs[other_agent] = outputs[-1].output

            return {
                "workflow_id": self.workflow_id,
                "current_phase": self._current_phase,
                "shared_state": dict(self._state),
                "recent_messages": [
                    {"from": m.from_agent, "content": m.content}
                    for m in recent_messages
                ],
                "other_agent_outputs": other_outputs
            }

    def clear(self) -> None:
        """Clear all data in the pool."""
        with self._lock:
            self._state.clear()
            self._state_metadata.clear()
            self._agent_outputs.clear()
            self._messages.clear()
            self._phase_history.clear()
            self._current_phase = ""
            # Keep registered_agents for reference

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        with self._lock:
            return {
                "workflow_id": self.workflow_id,
                "state_keys": len(self._state),
                "registered_agents": len(self._registered_agents),
                "total_outputs": sum(
                    len(outputs) for outputs in self._agent_outputs.values()
                ),
                "message_count": len(self._messages),
                "phases_completed": len(self._phase_history),
                "current_phase": self._current_phase,
                "age_seconds": (datetime.now() - self._created_at).total_seconds()
            }


def get_shared_pool(workflow_id: str) -> SharedMemoryPool:
    """
    Get or create a shared memory pool.

    Convenience wrapper around SharedMemoryPool.get_pool().

    Args:
        workflow_id: Workflow identifier

    Returns:
        SharedMemoryPool instance
    """
    return SharedMemoryPool.get_pool(workflow_id)


def cleanup_pools(max_age_hours: int = 24) -> int:
    """
    Clean up old workflow pools.

    Args:
        max_age_hours: Max pool age in hours

    Returns:
        Number of pools cleaned up
    """
    count = 0
    max_age_seconds = max_age_hours * 3600

    with SharedMemoryPool._global_lock:
        pools_to_remove = []
        for workflow_id, pool in SharedMemoryPool._instances.items():
            age = (datetime.now() - pool._created_at).total_seconds()
            if age > max_age_seconds:
                pools_to_remove.append(workflow_id)

        for workflow_id in pools_to_remove:
            del SharedMemoryPool._instances[workflow_id]
            count += 1

    return count
