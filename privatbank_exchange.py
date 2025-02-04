import aiohttp
import asyncio
import sys
import platform
from datetime import datetime, timedelta
import json
import argparse
from abc import ABC, abstractmethod
import aiofile
import websockets
import logging

# Установка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    filename="exchange_commands.log",
    filemode="a",
)


class CurrencyRatesFetcher(ABC):
    @abstractmethod
    async def fetch_rates(self, date: str, currencies: list) -> dict:
        pass


class PrivatBankCurrencyRatesFetcher(CurrencyRatesFetcher):
    BASE_URL = "https://api.privatbank.ua/p24api/exchange_rates"

    async def fetch_rates(self, date: str, currencies: list) -> dict:
        async with aiohttp.ClientSession() as session:
            params = {"json": "", "date": date}
            try:
                async with session.get(self.BASE_URL, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return self._parse_response(data, date, currencies)
            except aiohttp.ClientError as e:
                print(f"Error fetching data for {date}: {str(e)}")
                return {}

    def _parse_response(self, data: dict, date: str, currencies: list) -> dict:
        rates = {}
        for rate in data.get("exchangeRate", []):
            if rate.get("currency") in currencies:
                rates[rate["currency"]] = {
                    "sale": rate.get("saleRate"),
                    "purchase": rate.get("purchaseRate"),
                }
        return {date: rates} if rates else {}


class CurrencyRatesService:
    def __init__(self, fetcher: CurrencyRatesFetcher):
        self.fetcher = fetcher

    async def get_rates_for_days(self, days: int, currencies: list) -> list:
        if days < 1 or days > 10:
            raise ValueError("Number of days must be between 1 and 10")

        dates = [
            (datetime.now() - timedelta(days=i)).strftime("%d.%m.%Y")
            for i in range(days)
        ]
        tasks = [self.fetcher.fetch_rates(date, currencies) for date in dates]
        results = await asyncio.gather(*tasks)
        return [result for result in results if result]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch exchange rates from PrivatBank API"
    )
    parser.add_argument("days", type=int, help="Number of days to fetch (1-10)")
    parser.add_argument(
        "-c",
        "--currencies",
        type=str,
        default="EUR,USD",
        help="Comma separated list of currencies (default: EUR,USD)",
    )
    args = parser.parse_args()

    if args.days < 1 or args.days > 10:
        print("Error: Please provide a valid number of days (1-10)")
        sys.exit(1)

    currencies = args.currencies.split(",")
    return args.days, currencies


async def exchange_command(websocket, path):
    async for message in websocket:
        command = message.strip().split()
        if command[0] == "exchange":
            if len(command) == 1:
                await websocket.send(
                    "Please provide the number of days (1-10) for the exchange rates."
                )
            elif len(command) == 2:
                try:
                    days = int(command[1])
                    if 1 <= days <= 10:
                        fetcher = PrivatBankCurrencyRatesFetcher()
                        service = CurrencyRatesService(fetcher)
                        rates = await service.get_rates_for_days(days, ["EUR", "USD"])
                        await websocket.send(
                            json.dumps(rates, indent=2, ensure_ascii=False)
                        )
                        # Логируем команду
                        async with aiofile.AIOFile("exchange_commands.log", "a") as afp:
                            await afp.write(
                                f"{datetime.now()} - exchange {days} days command executed\n"
                            )
                    else:
                        await websocket.send(
                            "Error: The number of days must be between 1 and 10."
                        )
                except ValueError:
                    await websocket.send(
                        "Error: Please provide a valid number of days."
                    )
        else:
            await websocket.send("Invalid command. Use 'exchange <days>' to get rates.")


async def main():
    days, currencies = parse_args()
    fetcher = PrivatBankCurrencyRatesFetcher()
    service = CurrencyRatesService(fetcher)

    try:
        rates = await service.get_rates_for_days(days, currencies)
        print(json.dumps(rates, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"An error occurred: {str(e)}")


# Запуск веб-сокет сервера
async def start_websocket_server():
    server = await websockets.serve(exchange_command, "localhost", 8765)
    await server.wait_closed()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Запуск веб-сокет сервера и основной программы в одном асинхронном цикле
    loop = asyncio.get_event_loop()
    loop.create_task(start_websocket_server())  # Запуск сервера
    loop.run_until_complete(main())  # Запуск основной программы
