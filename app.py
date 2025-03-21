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

def retrieve_similar_messages(user_id, query_text, max_results=5, similarity_threshold=0.7):
    """Retrieve most relevant past messages using vector similarity search with threshold."""
    # Generate embedding for the query text
    query_embedding = generate_embedding(query_text)

    # Fetch all stored messages for the user with embeddings
    all_messages = list(collection.find({"user_id": user_id, "embedding": {"$exists": True}}))

    # Compute cosine similarity between query embedding and stored embeddings
    def cosine_similarity(vec1, vec2):
        vec1, vec2 = np.array(vec1), np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

    # Calculate similarity scores and filter by threshold
    ranked_messages = []
    for msg in all_messages:
        similarity = cosine_similarity(query_embedding, msg["embedding"])
        if similarity >= similarity_threshold:
            ranked_messages.append((msg, similarity))
    
    # Sort by similarity in descending order
    ranked_messages.sort(key=lambda x: x[1], reverse=True)
    
    # Return top N messages with role, content and similarity score
    return [{"role": msg[0]["role"], 
             "content": msg[0]["content"], 
             "similarity": msg[1]} 
            for msg in ranked_messages[:max_results]]

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
                retrieved_context = retrieve_similar_messages(user_id, user_message)
                
                # Format retrieved context as a separate context section
                context_str = ""
                if retrieved_context:
                    context_str = "### Relevant Context:\n"
                    for i, item in enumerate(retrieved_context):
                        context_str += f"{i+1}. {item['role'].capitalize()}: {item['content']}\n"
                
                # Current conversation - just the new user query
                current_message = {"role": "user", "content": user_message}
                
                # Create structured prompt with system message, context, and query
                system_message = (
                    "You are an AI assistant. Use the provided context to help answer "
                    "the user's question. If the context doesn't contain relevant information, "
                    "respond based on your general knowledge. Always cite which piece of context "
                    "you used in your answer if applicable."
                )
                
                messages = [
                    {"role": "system", "content": system_message}
                ]
                
                # Add context if available
                if context_str:
                    messages.append({"role": "system", "content": context_str})
                    
                # Add the current user query
                messages.append(current_message)

                # Get AI response
                response = client.chat.completions.create(
                    model="nvidia/Llama-3.1-Nemotron-70B-Instruct-HF-fast",
                    temperature=0,
                    messages=messages
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
def admin():
    """Admin dashboard to view and manage chat history."""
    try:
        # Fetch all messages from MongoDB
        messages = list(collection.find({}))
        
        # Group messages by user_id for processing
        user_messages = {}
        assistant_messages = {}
        
        # First, separate messages by role and user_id
        for msg in messages:
            user_id = msg.get("user_id")
            role = msg.get("role")
            
            if not user_id or not role:
                continue
                
            if role == "user":
                if user_id not in user_messages:
                    user_messages[user_id] = []
                user_messages[user_id].append(msg)
            elif role == "assistant":
                if user_id not in assistant_messages:
                    assistant_messages[user_id] = []
                assistant_messages[user_id].append(msg)
        
        # Format the data for the template
        history = []
        
        # For each user, pair their messages with responses
        for user_id, msgs in user_messages.items():
            # Sort messages by _id to maintain chronological order
            msgs.sort(key=lambda x: x["_id"])
            
            # Get assistant responses for this user
            responses = assistant_messages.get(user_id, [])
            responses.sort(key=lambda x: x["_id"])
            
            # Add each user message with its corresponding response
            for i, msg in enumerate(msgs):
                # Find the response that came after this message
                response_content = "No response"
                
                # Try to find a response with an ID greater than the user message ID
                for resp in responses:
                    if resp["_id"] > msg["_id"]:
                        response_content = resp.get("content", "No response")
                        # Remove this response so we don't use it again
                        responses.remove(resp)
                        break
                
                history.append({
                    "user_id": user_id,
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "response": response_content
                })
        
        # Debug info
        app.logger.info(f"Found {len(history)} entries for admin display")
        
        return render_template("admin.html", history=history)
    except Exception as e:
        # Log the error and return an error message
        app.logger.error(f"Error in admin route: {str(e)}")
        return render_template("admin.html", error=str(e))

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
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
