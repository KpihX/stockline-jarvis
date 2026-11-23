"""
Every tunable number of the vocabulary system, in ONE place.

Learning rules
  PROMOTE_MIN_CLIENTS  a (heard form → entity) pair confirmed for this many DISTINCT clients joins the global lexicon
  EXPIRE_UNUSED_DAYS   a learned entry confirmed only once and not seen again for this long is ignored (and pruned)
  EXPIRE_USED_DAYS     a learned entry confirmed 2+ times and not seen for this long is ignored (and pruned)
Resolver (scores are 0..1, see lexicon/phonetic.py; 1.0 = the exact spelling of a known form)
  ACCEPT_SCORE         at least this (and MIN_MARGIN over the runner-up) → "resolved": the mention is offered as a correction
  AMBIGUOUS_SCORE      at least this → "ambiguous": the agent must ask / offer to spell, never guess
  MIN_MARGIN           gap between the best and the second-best entity needed to call a mention resolved
  SINGLE_WORD_ACCEPT   stricter ACCEPT_SCORE for a one-word mention (more false-positive prone); SHORT_WORD_ACCEPT for 3 sounds or less
  CLIENT_BONUS / USUAL_BONUS  priors added to the score of a client's own entries / products they usually order
Decision (Jev, optional)
  JEV_MIN_CONFIDENCE   Jev must be at least this sure to settle an ambiguous mention; below, the agent asks
  JEV_TIMEOUT_S        a Jev call longer than this is abandoned (the LLM path continues)
Runtime
  CATALOGUE_TTL_S / CLIENT_TTL_S / LEARNED_TTL_S   cache lifetimes (ERP reads)
  HINT_CLIENT_WAIT_S   at most this long is spent waiting for a client's terms when a turn starts (else: global terms only)
  MAX_CLIENT_TERMS     STT terms put before the global ones once the caller is known
"""

PROMOTE_MIN_CLIENTS = 3
EXPIRE_UNUSED_DAYS = 30
EXPIRE_USED_DAYS = 180

ACCEPT_SCORE = 0.80
SINGLE_WORD_ACCEPT = 0.85
SHORT_WORD_ACCEPT = 0.90  # a one-word mention of 3 sounds or less ("diots"): even stricter
AMBIGUOUS_SCORE = 0.72
SINGLE_AMBIGUOUS_SCORE = 0.82  # ... for a one-word mention (short common words like "salle" look like "salade")
MIN_MARGIN = 0.06
CLIENT_BONUS = 0.03
USUAL_BONUS = 0.03

JEV_MIN_CONFIDENCE = 0.75
JEV_TIMEOUT_S = 1.2

CATALOGUE_TTL_S = 300
CLIENT_TTL_S = 120
LEARNED_TTL_S = 60
HINT_CLIENT_WAIT_S = 0.35
MAX_CLIENT_TERMS = 80

# Context-table convention: a learned entry is a context row with kind "fact" and this tag.
VOCAB_TAG = "vocab"
