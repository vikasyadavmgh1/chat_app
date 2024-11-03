from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import boto3
from botocore.exceptions import NoCredentialsError
from typing import Dict, List

app = FastAPI()

# Middleware for CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# AWS S3 configuration
AWS_ACCESS_KEY_ID = 'your_access_key_id'
AWS_SECRET_ACCESS_KEY = 'your_secret_access_key'
BUCKET_NAME = 'my-messaging-app-bucket'

# Initialize the S3 client
s3_client = boto3.client('s3', 
                          aws_access_key_id=AWS_ACCESS_KEY_ID, 
                          aws_secret_access_key=AWS_SECRET_ACCESS_KEY)

class ConnectionManager:
    def __init__(self):
        # Store connections by client ID for targeted messaging
        self.active_connections: Dict[str, WebSocket] = {}
        # Store messages for offline clients
        self.offline_messages: Dict[str, List[str]] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket

        # Check if there are any offline messages for this client
        if client_id in self.offline_messages:
            messages = self.offline_messages[client_id]
            for message in messages:
                await websocket.send_text(message)
            # Clear the messages after sending
            del self.offline_messages[client_id]

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_personal_message(self, message: str, client_id: str):
        """Send a message to a specific client."""
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            await websocket.send_text(message)
        else:
            # Store the message for the offline client
            if client_id not in self.offline_messages:
                self.offline_messages[client_id] = []
            self.offline_messages[client_id].append(message)

    async def broadcast(self, message: str):
        """Send a message to all connected clients."""
        for websocket in self.active_connections.values():
            await websocket.send_text(message)

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def main():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Upload Media</title>
    </head>
    <body>
        <h1>Upload Photo or Video to Send</h1>
        <form id="uploadForm" action="/uploadfile/" method="post" enctype="multipart/form-data">
            <label for="recipient">Enter Recipient ID:</label>
            <input type="text" id="recipient" name="recipient" placeholder="Recipient ID" required>
            <br><br>
            <label for="file">Select Photo or Video:</label>
            <input name="file" type="file" id="file" accept="image/*,video/*" required>
            <button type="submit">Upload</button>
        </form>
        <div id="response"></div>
        <script>
            const form = document.getElementById("uploadForm");
            form.onsubmit = async (event) => {
                event.preventDefault();
                const formData = new FormData(form);
                const response = await fetch(form.action, {
                    method: form.method,
                    body: formData,
                });
                const result = await response.json();
                if (result.url) {
                    document.getElementById("response").innerHTML = `Media uploaded! <a href="${result.url}" target="_blank">Download Link</a>`;
                    const recipientId = document.getElementById("recipient").value;
                    const socket = new WebSocket(`ws://localhost:8000/ws/${recipientId}`);
                    socket.onopen = () => {
                        socket.send(JSON.stringify({ message: `User has sent a media file!`, url: result.url }));
                    };
                } else {
                    console.error(result.error);
                    document.getElementById("response").innerText = "Error uploading media.";
                }
            };
        </script>
    </body>
    </html>
    """)

@app.post("/uploadfile/")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_location = file.filename
        s3_client.upload_fileobj(file.file, BUCKET_NAME, file_location)
        file_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{file_location}"
        return {"filename": file.filename, "url": file_url}
    except NoCredentialsError:
        return {"error": "Credentials not available."}
    except Exception as e:
        return {"error": str(e)}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    # Connect the client
    await manager.connect(client_id, websocket)
    try:
        while True:
            # Wait for a message from the client
            data = await websocket.receive_text()

            # Parse the message to get recipient_id and the actual message text
            if ":" in data:
                recipient_id, message = data.split(":", 1)
                # Send the message to the specified recipient
                await manager.send_personal_message(f"Message from {client_id}: {message}", recipient_id)
            else:
                # If the message is incorrectly formatted, send an error back
                await websocket.send_text("Error: Message format should be 'recipient_id:message'")

    except WebSocketDisconnect:
        # Disconnect the client if they disconnect
        manager.disconnect(client_id)
        await manager.broadcast(f"Client {client_id} has left the chat")

@app.on_event("shutdown")
async def shutdown_event():
    print("Server shutting down...")  # Handle cleanup here if necessary