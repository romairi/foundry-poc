"""

Tool: Get Weather

The agent calls this function when the user asks about weather.

"""

import json



def get_weather(city: str) -> str:

    """

    Get current weather for a city.



    :param city: City name, e.g. 'Moscow', 'Tel Aviv', 'New York'

    :return: Weather information as JSON string.

    """



    # Fake data (replace with real API like OpenWeatherMap in production)

    fake_data = {

        "Moscow": {"temp": 18, "condition": "cloudy"},

        "Tel Aviv": {"temp": 32, "condition": "sunny"},

        "New York": {"temp": 24, "condition": "partly cloudy"},

    }



    weather = fake_data.get(city, {"temp": 20, "condition": "no data"})



    return json.dumps({

        "city": city,

        "temperature": f"{weather['temp']}°C",

        "condition": weather["condition"]

    }, ensure_ascii=False)



