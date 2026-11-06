"""A2A Message Bus and Inter-Framework Router."""

import logging
import threading
from typing import Callable, Dict, List, Optional
from core.a2a.envelope import A2AEnvelope

logger = logging.getLogger("A2ABus")


class A2ABus:
    """Agent-to-Agent communication bus routing messages between CrewAI and Google ADK agents."""

    def __init__(self):
        self._lock = threading.RLock()
        self._registry: Dict[str, Callable[[A2AEnvelope], Optional[A2AEnvelope]]] = {}
        self._message_history: List[A2AEnvelope] = []
        self._listeners: List[Callable[[A2AEnvelope], None]] = []

    def register_agent(
        self,
        agent_id: str,
        handler: Callable[[A2AEnvelope], Optional[A2AEnvelope]],
    ) -> None:
        """Register an agent endpoint on the A2A bus."""
        with self._lock:
            self._registry[agent_id] = handler
            logger.info(f"Registered A2A agent: {agent_id}")

    def unregister_agent(self, agent_id: str) -> None:
        with self._lock:
            if agent_id in self._registry:
                del self._registry[agent_id]

    def add_listener(self, listener: Callable[[A2AEnvelope], None]) -> None:
        """Global listener for telemetry, logging, and dashboard updates."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def dispatch(self, envelope: A2AEnvelope) -> Optional[A2AEnvelope]:
        """Dispatch a message envelope to target agent(s) or broadcast."""
        with self._lock:
            # Verify integrity
            if not envelope.verify_integrity():
                raise ValueError(f"A2A Message {envelope.message_id} failed integrity verification!")

            self._message_history.append(envelope)

            # Notify telemetry listeners
            for listener in list(self._listeners):
                try:
                    listener(envelope)
                except Exception as e:
                    logger.warning(f"Error in A2A listener: {e}")

            # Routing
            if envelope.recipient_id == "*":
                # Broadcast
                for agent_id, handler in self._registry.items():
                    if agent_id != envelope.sender_id:
                        try:
                            handler(envelope)
                        except Exception as e:
                            logger.error(f"Error delivering broadcast to {agent_id}: {e}")
                return None
            else:
                # Point-to-point delivery
                handler = self._registry.get(envelope.recipient_id)
                if not handler:
                    logger.warning(
                        f"A2A Recipient '{envelope.recipient_id}' not found in registry. "
                        f"Active: {list(self._registry.keys())}"
                    )
                    return None
                try:
                    response = handler(envelope)
                    if response:
                        if not response.verify_integrity():
                            raise ValueError("A2A Response signature invalid!")
                        self._message_history.append(response)
                        for listener in list(self._listeners):
                            try:
                                listener(response)
                            except Exception:
                                pass
                    return response
                except Exception as e:
                    logger.error(f"Error processing A2A envelope at {envelope.recipient_id}: {e}")
                    raise

    def get_history(self) -> List[A2AEnvelope]:
        with self._lock:
            return list(self._message_history)

    def clear(self) -> None:
        with self._lock:
            self._message_history.clear()


# Global A2A bus singleton
global_a2a_bus = A2ABus()

