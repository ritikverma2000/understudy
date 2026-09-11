"""Flask application that stands in for a legacy banking surface."""

from __future__ import annotations

from decimal import Decimal

from flask import Flask, abort, render_template, request, url_for

from target_app.data import MEMBERS


def format_usd(cents: int) -> str:
    """Render integer cents without introducing floating-point arithmetic."""
    amount = Decimal(cents) / Decimal(100)
    return f"${amount:,.2f}"


def create_app(*, testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config.update(TESTING=testing)
    app.jinja_env.filters["usd"] = format_usd

    @app.get("/")
    def index() -> tuple[str, int, dict[str, str]]:
        return "", 302, {"Location": "/app"}

    @app.get("/app")
    def app_shell() -> str:
        inject = request.args.get("inject")
        workspace_src = url_for("member_search", inject=inject)
        return render_template(
            "app_shell.html",
            workspace_src=workspace_src,
        )

    @app.get("/workspace/search")
    def member_search() -> str:
        if request.args.get("inject") == "expired":
            return render_template("session_expired.html")
        return render_template("member_search.html")

    @app.get("/workspace/results")
    def member_results() -> str:
        member_id = request.args.get("f_003", "").strip()
        member = MEMBERS.get(member_id)

        return render_template(
            "member_results.html",
            member_id=member_id,
            member=member,
        )

    @app.get("/workspace/member/<member_id>")
    def member_detail(member_id: str) -> str:
        member = MEMBERS.get(member_id)
        if member is None:
            abort(404)

        return render_template(
            "member_detail.html",
            member_id=member_id,
            member=member,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
