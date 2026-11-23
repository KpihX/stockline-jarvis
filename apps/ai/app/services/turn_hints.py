"""
Cheap, deterministic judgement made the moment the FINAL transcript is available, before the model is called:
"will this turn probably need the ERP (a tool round, 2-5 s of silence)?". If so the voice session plays its canned filler
right away instead of waiting for the model to ask for a tool (GUIDE-VOIX.md 4.7).

Pure Python, microseconds, no I/O. It is a heuristic: a wrong YES costs one short "Je regarde." before a direct answer; a wrong
NO costs nothing (the filler still plays at the first tool call, as before).

Skipped on purpose:
  - trivial turns (greeting, thanks, yes / no, goodbye): the answer is instant, a filler would only delay it;
  - when a filler was played less than FILLER_MIN_GAP_S ago (the caller was reassured a moment ago: a "Je regarde." every
    few seconds of a fast order-taking exchange is irritating).
"""

import re

from app.config import env

FILLER_MIN_GAP_S = 10.0

# Kill-switches (default ON). VOICE_EARLY_FILLER=0: no filler at the transcript, only at the tool call (the V0 behaviour).
# VOICE_TOOL_START=0: the voice session does not react to the start of a tool_use block, only to the complete call.
EARLY_FILLER = env("VOICE_EARLY_FILLER", "1") != "0"
TOOL_START = env("VOICE_TOOL_START", "1") != "0"

# accents folded, lowercase
TOOL_WORDS = re.compile(
    r"\b(stock|stocks|prix|tarif|tarifs|combien|commande|commandes|commander|quantite|quantites|kilo|kilos|kg|caisse|caisses|carton|cartons|"
    r"colis|piece|pieces|disponible|disponibilite|reste|avez|livraison|livrer|livre|facture|factures|encours|solde|habitude|d'hab|habituel|"
    r"ajoute|ajouter|enleve|supprime|annule|annuler|confirme|confirmer|valide|valider|modifie|change|remplace|historique|fiche|client|"
    r"produit|rupture|arrivage|alternative|equivalent|credit|paiement|impaye|tournee|demain|apres-demain|lundi|mardi|mercredi|jeudi|vendredi|samedi)\b"
)
_PHRASES = (
    r"bonjour|bonsoir|salut|allo|allo allo|hello|coucou|merci|merci beaucoup|merci bien|d'accord|ok|okay|oui|non|si|ouais|nan|bien sur|"
    r"parfait|tres bien|super|excellent|nickel|impeccable|entendu|compris|c'est bon|c'est tout|c'est note|ca marche|ca roule|"
    r"au revoir|a bientot|bonne journee|bonne soiree|bonne continuation|a demain|a plus|bye|pardon|excusez-moi|euh|hum|"
    r"vous m'entendez|tu m'entends|ca va|comment allez-vous|comment vas-tu"
)
TRIVIAL = re.compile(rf"^(?:{_PHRASES})$")
# the same phrases chained together (with a few connectors): "oui merci", "au revoir et bonne journee"
CHAIN = re.compile(rf"^(?:(?:{_PHRASES}|et|alors|donc|bien|tres)(?:\s+|$))+$")
FOLD = str.maketrans("àâäçéèêëîïôöùûüÿœ’", "aaaceeeeiioouuuyo'")


def fold(text: str) -> str:
    """Lowercase, accents and punctuation (but not apostrophes, hyphens, digits or decimal commas) removed, spaces collapsed."""
    text = text.lower().translate(FOLD)
    text = re.sub(r"[^\w\s'’-]", " ", text)
    return " ".join(text.split())


def is_trivial(text: str) -> bool:
    """Greeting / thanks / yes-no / goodbye, alone or chained ("oui merci", "bonjour allo"): nothing to look up."""
    t = fold(text)
    if not t:
        return True
    if TRIVIAL.match(t):
        return True
    return len(t.split()) <= 8 and bool(CHAIN.match(t))  # "oui merci beaucoup", "au revoir et bonne journée"


def likely_needs_tools(text: str) -> bool:
    t = fold(text)
    if is_trivial(t):
        return False
    if TOOL_WORDS.search(t) or re.search(r"\d", t):  # a business word, or a number (quantity, price, date, order number)
        return True
    return len(t.split()) >= 5  # a real sentence that matches nothing above: more likely a request than small talk


def should_prefill(text: str, since_last_filler_s: float | None) -> bool:
    """Play the filler now? `since_last_filler_s`: seconds since the last filler of this connection (None = never)."""
    if not EARLY_FILLER or (since_last_filler_s is not None and since_last_filler_s < FILLER_MIN_GAP_S):
        return False
    return likely_needs_tools(text)
