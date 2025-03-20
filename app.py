from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import os
from openai import OpenAI
from pymongo import MongoClient
import numpy as np
from bson.objectid import ObjectId  # Import for generating unique user IDs

app = Flask(__name__)
app.secret_key = "your_secret_key"  # For session management

# Connect to MongoDB Atlas
client_db = MongoClient(os.environ.get("MONGODB_ATLAS_URI"))
db = client_db["chatbot"]
collection = db["chat_history"]

# Initialize Nebius AI Client
client = OpenAI(
    base_url="https://api.studio.nebius.com/v1/",
    api_key=os.environ.get("NEBIUS_API_KEY")
)

def generate_embedding(text):
    """Generate embeddings using Nebius AI."""
    # Call Nebius API to generate a vector embedding for the input text
    response = client.embeddings.create(
        model="BAAI/bge-en-icl",
        input=text
    )
    return response.data[0].embedding  # Extract vector from API response

def retrieve_similar_messages(user_id, query_text, max_results=5):
    """Retrieve most relevant past messages using vector similarity search."""
    # Generate embedding for the query text
    query_embedding = generate_embedding(query_text)

    # Fetch all stored messages for the user with embeddings
    all_messages = list(collection.find({"user_id": user_id, "embedding": {"$exists": True}}))

    # Compute cosine similarity between query embedding and stored embeddings
    def cosine_similarity(vec1, vec2):
        vec1, vec2 = np.array(vec1), np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

    # Rank messages by similarity in descending order
    ranked_messages = sorted(
        all_messages,
        key=lambda msg: cosine_similarity(query_embedding, msg["embedding"]),
        reverse=True
    )

    # Return top N messages with role and content
    return [{"role": msg["role"], "content": msg["content"]} for msg in ranked_messages[:max_results]]

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Handle user sign-up."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # Replace with proper user creation logic (e.g., hashing passwords)
        if username and password:
            user_id = str(ObjectId())  # Generate a unique user ID
            db["users"].insert_one({"_id": user_id, "username": username, "password": password})
            session["user_id"] = user_id  # Store user ID in session
            return redirect(url_for("index"))
        return "Invalid input", 400
    return render_template("signup.html")

@app.route("/login", methods=["POST", "GET"])
def login():
    """Handle user login."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # Replace with proper authentication logic
        user = db["users"].find_one({"username": username, "password": password})
        if user:
            session["user_authenticated"] = True
            session["user_id"] = str(user["_id"])  # Store user ID in session
            return redirect(url_for("index"))
        return "Invalid credentials", 401
    return render_template("login.html")

@app.route("/logout", methods=["GET"])
def logout():
    """Handle user logout."""
    session.pop("user_authenticated", None)
    session.pop("user_id", None)  # Remove user ID from session
    return redirect(url_for("index"))

@app.route("/clear_history", methods=["POST"])
def clear_history():
    """Clear chat history for the current user."""
    try:
        user_id = session.get("user_id")  # Get user ID from session
        if not user_id:
            return jsonify({"success": False, "error": "User not authenticated"})
        collection.delete_many({"user_id": user_id})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/home", methods=["GET"])
def home():
    """Home page with site details and navigation options."""
    return render_template("home.html")

@app.route("/", methods=["GET"])
def root():
    """Redirect the root URL to the home page."""
    return redirect(url_for("home"))

@app.route("/index", methods=["GET", "POST"])
def index():
    """Main route for user interaction."""
    user_authenticated = session.get("user_authenticated", False)
    if not user_authenticated:
        return redirect(url_for("home"))  # Redirect to home page if not authenticated

    user_id = session.get("user_id")  # Get user ID from session
    if not user_id:
        return redirect(url_for("home"))  # Redirect to home page if not authenticated

    response_data = None
    user_message = ""

    if request.method == "POST":
        user_message = request.form.get("user_message")
        if user_message:
            try:
                # Retrieve similar past messages using embeddings
                past_messages = retrieve_similar_messages(user_id, user_message)

                # Add the latest user message
                past_messages.append({"role": "user", "content": user_message})

                # Get AI response
                response = client.chat.completions.create(
                    model="meta-llama/Llama-3.2-3B-Instruct",
                    temperature=0,
                    messages=[
                        {"role": "system", "content": "You are an AI assistant."}
                    ] + past_messages
                )

                ai_response = response.choices[0].message.content

                # Generate embedding for new user message
                user_embedding = generate_embedding(user_message)

                # Store user and AI responses in MongoDB
                collection.insert_one({"user_id": user_id, "role": "user", "content": user_message, "embedding": user_embedding})
                collection.insert_one({"user_id": user_id, "role": "assistant", "content": ai_response, "embedding": generate_embedding(ai_response)})

                response_data = {"content": ai_response}

            except Exception as e:
                response_data = {"error": str(e)}

    return render_template("index.html", response=response_data, user_message=user_message, user_authenticated=True)

@app.route("/admin", methods=["GET"])
def admin_dashboard():
    """Admin route to view all messages and embeddings."""
    try:
        # Fetch all messages from the database
        all_messages = list(collection.find())

        # Truncate embeddings for display
        for message in all_messages:
            if "embedding" in message:
                message["embedding_preview"] = str(message["embedding"][:10]) + "..."  # Show first 10 values
                message["embedding_full"] = message["embedding"]  # Store full embedding for "Show More"

        # Render the admin dashboard with all messages
        return render_template("admin.html", messages=all_messages)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/delete_message", methods=["POST"])
def delete_message():
    """Delete a specific message from the database."""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        role = data.get("role")

        if not user_id or not role:
            return jsonify({"success": False, "error": "Invalid input"})

        # Delete the message from the database
        result = collection.delete_one({"user_id": user_id, "role": role})

        if result.deleted_count > 0:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Message not found"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    app.run(debug=True)
