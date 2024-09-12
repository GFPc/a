import logging
import asyncio
from typing import Dict, Optional
from telethon import TelegramClient, events
from pydantic import BaseModel, ValidationError
import config
import aiohttp

logging.basicConfig(level=logging.INFO)

API_ID = config.API_ID
API_HASH = config.API_HASH
SESSION_NAME = config.SESSION_NAME
PHONE_NUMBER = config.PHONE_NUMBER
SOURCES = config.SOURCES

CLIENT_TOKEN = config.CLIENT_TOKEN
CLIENT_HASH = config.CLIENT_HASH

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

url_prefix = "https://ibronevik.ru/taxi/c/gruzvill/api/v1/"

class Order(BaseModel):
    date: str
    time: str
    start_location: str = "Точка А"
    end_location: str = "Точка Б"
    vehicle_type: str = "Неизвестно"
    price: int = 0
    passengers: int = 0
    order_number: int = 0

original_message_cache: Dict[int, int] = {}

async def send_api_request(endpoint: str, data: dict) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.post(url_prefix + endpoint, json=data) as response:
            response_data = await response.json()
            return response_data

async def process_message(message: str, event) -> Optional[Order]:
    print(await event.message.get_buttons())

    try:
        lines = message.split('\n')
        date_time = lines[0].split()
        locations = lines[1].split(' - ') if len(lines) > 1 else ["Точка А", "Точка Б"]
        vehicle_info = lines[2].split() if len(lines) > 2 else ["Неизвестно", "0₽", "", "0", "", "№: 0"]
        
        order = Order(
            date=date_time[0],
            time=date_time[1],
            start_location=locations[0],
            end_location=locations[1],
            vehicle_type=vehicle_info[0],
            price=int(vehicle_info[1].replace('₽', '')),
            passengers=int(vehicle_info[3]),
            order_number=int(vehicle_info[5].replace('№: ', ''))
        )
        
        original_message_cache[event.message.id] = event.message.id
        
        return order
    except (IndexError, ValueError, ValidationError) as e:
        logging.error(f"Error processing message: {e}")
        return None

async def send_order_request(order: Order, original_message_id: int):
    message = (
        f"token: your_token\n"
        f"u_hash: your_u_hash\n"
        f"data:\n"
        f"  b_start_address: {order.start_location}\n"
        f"  b_start_latitude: \n"
        f"  b_start_longitude: \n"
        f"  b_destination_address: {order.end_location}\n"
        f"  b_destination_latitude: \n"
        f"  b_destination_longitude: \n"
        f"  b_comments: []\n"
        f"  b_contact: \n"
        f"  b_start_datetime: {order.date} {order.time}\n"
        f"  b_passengers_count: {order.passengers}\n"
        f"  b_car_class: {order.vehicle_type}\n"
        f"  b_payment_way: 1\n"
        f"  b_max_waiting: 7200\n"
        f"  b_services: []\n"
    )

    response_data = await send_api_request("drive", message)
    b_id = response_data["b_id"]
    logging.info(f"Created order with b_id: {b_id}")
    
async def accept_order(event):

    for original_message_id in original_message_cache:

        original_message = await client.get_messages(event.chat_id, ids=original_message_id)
            
        try:
            await original_message.click(0)
            logging.info("Clicked 'Взять заказ'.")
        except Exception as e:
            logging.error(f"Error clicking 'Взять заказ': {e}")
        break

    @client.on(events.NewMessage(from_users=SOURCES))
    async def new_message_from_sources(event):
        if event.reply_markup:
            try:
                await event.message.click(0)
                logging.info("Clicked '✅Да, взять заказ'.")
            except Exception as e:
                logging.error(f"Error clicking '✅Да, взять заказ': {e}")
            return
    return

async def compare_offers_with_active_orders(response_data: dict, incoming_offer: Order) -> Optional[str]:
    for order_id, order_data in response_data["data"].items():
        active_offers = order_data["b_offers"]
        for offer in active_offers:
            active_offer = Order(
                date=offer["date"],
                time=offer["time"],
                start_location=offer["start_location"],
                end_location=offer["end_location"],
                vehicle_type=offer["vehicle_type"],
                price=int(offer["price"]),
                passengers=int(offer["passengers"]),
                order_number=int(offer["order_number"])
            )
            if active_offer == incoming_offer:
                return order_id 
    return None  

async def handle_order(order: Order):
    endpoint = "drive?fields=000000002"
    post_obj = {
        "token": CLIENT_TOKEN,
        "u_hash": CLIENT_HASH
    }
    
    response_data = await send_api_request(endpoint, post_obj)
    
    order_id = await compare_offers_with_active_orders(response_data, order)
    
    if order_id is None:
        logging.error("Order ID not found.")
        return

    b_offers = response_data["data"][order_id]["b_offers"]
            
    if b_offers:
        logging.info(f"Driver accepted the order. Offers: {b_offers}")
        await accept_order() 
    else:
        logging.info("No driver has accepted the order yet. Continuing to monitor...")

async def check_order_acceptance(order: Order, original_message_id: int):
    start_time = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start_time) < 300:  # 300 секунд = 5 минут
        await handle_order(order)
        await asyncio.sleep(5)  # ждать 5 секунд между проверками

@client.on(events.NewMessage)
async def new_message_handler(event):
    message_text = event.raw_text

    order = await process_message(message_text, event)
    if order:
        await send_order_request(order, event.message.id)
        asyncio.create_task(check_order_acceptance(order, event.message.id))

async def main():
    await client.start(phone=PHONE_NUMBER)
    logging.info("Telegram client started.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
