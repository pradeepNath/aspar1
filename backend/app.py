import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from config.db import test_connection
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

load_dotenv()

app = Flask(__name__)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS(app, origins=[frontend_url, "http://localhost:5173"])


@app.route("/api/health", methods=["GET"])
def health_check():
    db_ok = test_connection()
    return jsonify({
        "status": "ok",
        "database": "connected" if db_ok else "unreachable"
    }), 200


from routes.auth            import auth_bp
from routes.profile         import profile_bp
from routes.academic_upload import academic_upload_bp
from routes.quiz            import quiz_bp
from routes.grading         import grading_bp
from routes.skills          import skills_bp
from routes.roadmap         import roadmap_bp
from routes.progress        import progress_bp
from routes.career          import career_bp

app.register_blueprint(auth_bp,            url_prefix="/api/auth")
app.register_blueprint(profile_bp,         url_prefix="/api")
app.register_blueprint(academic_upload_bp, url_prefix="/api")
app.register_blueprint(quiz_bp,            url_prefix="/api")
app.register_blueprint(grading_bp,         url_prefix="/api")
app.register_blueprint(skills_bp,          url_prefix="/api")
app.register_blueprint(roadmap_bp,         url_prefix="/api")
app.register_blueprint(progress_bp,        url_prefix="/api")
app.register_blueprint(career_bp,          url_prefix="/api")


if __name__ == "__main__":
    port  = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "False") == "True"
    app.run(host="0.0.0.0", port=port, debug=debug)