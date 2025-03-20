// Create a MongoDB collection named "chat_history" with schema validation
db.createCollection("chat_history", {
  validator: {
    $jsonSchema: {
      bsonType: "object", // The document must be an object
      required: ["user_id", "role", "content", "embedding"], // Required fields
      properties: {
        user_id: {
          bsonType: "string", // User ID must be a string
          description: "User ID"
        },
        role: {
          bsonType: "string", // Role must be a string
          enum: ["user", "assistant"], // Allowed values: "user" or "assistant"
          description: "Message sender role"
        },
        content: {
          bsonType: "string", // Message content must be a string
          description: "Message content"
        },
        embedding: {
          bsonType: "array", // Embedding must be an array of numbers
          items: {
            bsonType: "double" // Each item in the array must be a double
          },
          description: "Vector embedding for the message"
        },
        timestamp: {
          bsonType: "date", // Timestamp must be a date
          description: "Timestamp of the message"
        }
      }
    }
  }
});
