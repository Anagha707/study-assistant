from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Document
from . import agent


def _doc_id(request, raw):
    """Returns (doc_id or None, error_response or None)."""
    if not raw:
        return None, None
    try:
        d = Document.objects.get(id=int(raw), user=request.user)
        return d.id, None
    except (Document.DoesNotExist, ValueError, TypeError):
        return None, Response({"error": "document not found"}, status=404)


@api_view(["POST"])
def agent_run(request):
    msg = (request.data.get("message") or "").strip()[:500]
    if len(msg) < 3:
        return Response({"error": "message required"}, status=400)
    doc_id, err = _doc_id(request, request.data.get("doc_id"))
    if err:
        return err
    if not Document.objects.filter(user=request.user, status="indexed").exists():
        return Response({"error": "Upload a document and wait for 'indexed' first"}, status=400)
    try:
        state = agent.run_agent(request.user.id, doc_id, msg)
    except Exception as e:
        return Response({"error": f"Agent error: {e}"}, status=500)
    return Response(agent.to_response(state))


@api_view(["POST"])
def agent_adapt(request):
    results = request.data.get("results")
    if not isinstance(results, list) or not results or len(results) > 20:
        return Response({"error": "results required (1-20 items)"}, status=400)
    doc_id, err = _doc_id(request, request.data.get("doc_id"))
    if err:
        return err

    ev = agent.evaluate(results)          # plain Python, no LLM
    header = f"### Your score: {ev['score']} / {ev['total']}\n\n"

    if not ev["weak"]:
        return Response({
            "steps": [{"tool": "evaluate", "note": "No weak topics found"}],
            "reply": header + "Perfect. No weak topics, so you're ready. Good luck! 🎉",
            "quiz": None, "sources": [], "evaluation": ev,
        })

    try:
        state = agent.run_agent(request.user.id, doc_id, agent.adapt_prompt(ev), mode="adapt")
    except Exception as e:
        return Response({"error": f"Agent error: {e}"}, status=500)

    out = agent.to_response(state)
    out["steps"] = [{"tool": "evaluate",
                     "note": f"Scored {ev['score']}/{ev['total']}, weak: {', '.join(ev['weak'])}"}] + out["steps"]
    out["reply"] = header + f"Weak topics: **{', '.join(ev['weak'])}**\n\n" + out["reply"]
    out["evaluation"] = ev
    return Response(out)