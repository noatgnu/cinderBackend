from channels.generic.websocket import AsyncJsonWebsocketConsumer


class SearchConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']

        await self.channel_layer.group_add(
            "search_" + self.session_id,
            self.channel_name
        )

        await self.accept()
        await self.send_json({
            "message": {"type": "notification", "content": "Connected to search session."}
        })

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "search_" + self.session_id,
            self.channel_name
        )

    async def receive_json(self, content, **kwargs):
        await self.channel_layer.group_send(
            "search_" + self.session_id,
            {
                "type": "search_message",
                "message": content
            }
        )

    async def search_message(self, event):
        message = event['message']
        await self.send_json(message)