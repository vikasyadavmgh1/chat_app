# main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List

app = FastAPI()

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