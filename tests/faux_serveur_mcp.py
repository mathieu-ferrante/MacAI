"""Serveur MCP minimal pour les tests (stdio, JSON-RPC)."""
import json
import sys

OUTILS = [
    {"name": "redimensionner", "description": "Redimensionne une image",
     "inputSchema": {"type": "object", "properties": {"chemin": {"type": "string"}, "largeur": {"type": "integer"}},
                     "required": ["chemin", "largeur"]}},
    {"name": "infos", "description": "Infos sur le logiciel", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "effacer_tout", "description": "Efface", "annotations": {"destructiveHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
]

print("journal du serveur sur stdout, à ignorer", flush=True)
for ligne in sys.stdin:
    msg = json.loads(ligne)
    if "id" not in msg:
        continue
    m, p = msg["method"], msg.get("params", {})
    if m == "initialize":
        res = {"protocolVersion": p["protocolVersion"], "capabilities": {"tools": {}},
               "serverInfo": {"name": "PhotoCraft", "version": "0.1"}}
    elif m == "tools/list":
        res = {"tools": OUTILS}
    elif m == "tools/call":
        if p["name"] == "redimensionner":
            res = {"content": [{"type": "text", "text": f"{p['arguments']['chemin']} → {p['arguments']['largeur']} px"}]}
        else:
            res = {"content": [{"type": "text", "text": "erreur simulée"}], "isError": True}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "inconnu"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
