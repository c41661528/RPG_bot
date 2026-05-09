"""
Ad-hoc party system — temporary teams that disband after one activity.

Parties live in memory only (lost on bot restart, by design). The PartyCog
owns the dict; this module just holds the data classes and constants.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

MAX_PARTY_SIZE       = 4
PARTY_TIMEOUT_SEC    = 60 * 60      # idle parties auto-cleanup after 60 min
INVITE_TIMEOUT_SEC   = 60           # invite buttons expire after 60 s
PARTY_REWARD_MULT    = 1.5          # each member gets 1.5× single-player rewards
ENEMY_HP_PER_MEMBER  = 0.5          # enemy HP scaling per extra member


@dataclass
class PartyMember:
    discord_user_id: int
    character_id:    int
    name:            str
    level:           int


@dataclass
class Party:
    leader_id: int                                 # discord user id
    members:   dict[int, PartyMember]              # discord user id → PartyMember
    pending_invites:      set[int] = field(default_factory=set)
    created_at:           float    = field(default_factory=time.time)
    activity_in_progress: bool     = False

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def is_full(self) -> bool:
        return self.size >= MAX_PARTY_SIZE

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > PARTY_TIMEOUT_SEC

    def hp_scale_factor(self) -> float:
        """Enemy HP multiplier for this party size (1 + 0.5×(N−1))."""
        return 1.0 + ENEMY_HP_PER_MEMBER * max(0, self.size - 1)

    def avg_level(self) -> int:
        if not self.members:
            return 1
        return max(1, int(sum(m.level for m in self.members.values()) / self.size))
