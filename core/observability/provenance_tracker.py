"""Cryptographic Provenance and Lineage Tracker."""

import hashlib
import json
from typing import List, Optional, Dict, Any

from core.schemas import ProvenanceRecord
from core.blackboard import global_blackboard


class ProvenanceTracker:
    """Maintains a tamper-evident SHA-256 chained log of agent actions and state mutations."""

    def __init__(self):
        self._chain: List[ProvenanceRecord] = []

    @property
    def chain(self) -> List[ProvenanceRecord]:
        return list(self._chain)

    def record_step(
        self,
        step_id: str,
        agent_id: str,
        framework: str,
        action_type: str,
        input_payload: Dict[str, Any],
        output_payload: Dict[str, Any],
        state_version: int,
    ) -> ProvenanceRecord:
        """Records an atomic step, cryptographically linking to previous block."""
        parent_hash = self._chain[-1].record_hash if self._chain else None

        in_hash = hashlib.sha256(json.dumps(input_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        out_hash = hashlib.sha256(json.dumps(output_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        record = ProvenanceRecord(
            step_id=step_id,
            parent_step_id=parent_hash,
            agent_id=agent_id,
            framework=framework,
            action_type=action_type,
            input_payload_hash=in_hash,
            output_payload_hash=out_hash,
            state_version=state_version,
        )
        record.record_hash = record.compute_hash()

        self._chain.append(record)
        global_blackboard.post_provenance_record(record)
        return record

    def verify_chain_integrity(self) -> bool:
        """Verifies that all links and hashes in the chain are valid and untampered."""
        if not self._chain:
            return True

        for i, block in enumerate(self._chain):
            # Verify block's own hash
            if block.record_hash != block.compute_hash():
                return False
            # Verify parent link
            if i > 0:
                expected_parent = self._chain[i - 1].record_hash
                if block.parent_step_id != expected_parent:
                    return False
            else:
                if block.parent_step_id is not None:
                    return False

        return True

    def clear(self) -> None:
        self._chain.clear()


# Global Provenance Tracker
provenance_tracker = ProvenanceTracker()

