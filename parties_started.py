#!/usr/bin/env python
# -*- coding: utf8 -*-

import lxml.html
import requests
from lxml import etree
import sys
import tweepy
import pickle
import io
import collections
from PIL import Image


def get_parties():
    site = "https://www.electoralcommission.org.uk/who-we-are-and-what-we-do/party-registration-applications/view-current-applications"
    response = requests.get(site)

    root = lxml.html.fromstring(response.content)

    parties = []

    content_nodes = root.xpath('//div[@class="c-accordion"]')
    for node in content_nodes:
        name = None
        area = None
        descriptions = []
        emblems = []

        h3_nodes = node.xpath(".//h3")
        name = h3_nodes[0].text_content().strip().replace("’", "'")
        old_name = None

        new_party = False
        new_name = None
        p_nodes = node.xpath(".//div/p")
        for pnode in p_nodes:
            strong_node = pnode.xpath("strong")
            if strong_node:
                key = strong_node[0].text.strip().lower()
                if (key == "proposed name:" or key == "proposed name (in english):") and not new_name:
                    if strong_node[
                        0
                    ].tail:  # Occasionally they'll accidentally make this an <li> after "proposed name", skip it for now
                        new_name = strong_node[0].tail.strip().replace("’", "'")
                        if new_name == name:
                            new_party = True
                        else:
                            old_name = name

                        name = new_name

                elif key == "part of the uk that this application applies to:":
                    if strong_node[0].tail:
                        area = strong_node[0].tail.strip()

        descriptions = []
        for li in node.xpath(".//li"):
            description = li.text_content().strip()
            if description.lower() != name.lower():
                descriptions.append(description)

        emblems = collections.OrderedDict()
        for img in node.xpath(".//img"):
            url = (
                "https://www.electoralcommission.org.uk"
                + img.attrib.get("srcset", img.attrib.get("data-srcset")).split(" ")[0]
            )
            emblems[url] = {"url": url, "description": img.attrib.get("alt").strip()}

        parties.append(
            {
                "name": name,
                "old_name": old_name,
                "area": area,
                "descriptions": descriptions,
                "emblems": list(emblems.values()),
                "new_party": new_party,
            }
        )

    return parties


PICKLEFILE = "partiesstarted.dat"

CONSUMER_KEY = "XXXXX"  # Twitter key
CONSUMER_SECRET = "XXXXX"  # Twitter secret

auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
try:
    data = pickle.load(open(PICKLEFILE, "rb"))
except IOError:
    data = {"last-modified": ""}

if "token" not in data:
    print(
        "\nOpen this URL and, then input the PIN you are given.\n\n\t%s\n"
        % auth.get_authorization_url()
    )
    pin = input("PIN: ").strip()

    token = auth.get_access_token(verifier=pin)
    if token:
        data["token"] = (auth.access_token, auth.access_token_secret)
        pickle.dump(data, open(PICKLEFILE, "wb"))

if "tweeted" not in data:
    data["tweeted"] = []

parties = get_parties()
for party in reversed(parties):

    if not party["new_party"] and not party["old_name"]:
        print("Skipping '%s': Not new or changed name" % party["name"])
        continue

    if party["name"] in data["tweeted"]:
        print("Skipping '%s': Already tweeted" % party["name"])
        continue

    data["tweeted"].append(party["name"])
    pickle.dump(data, open(PICKLEFILE, "wb"))

    message = None
    if party["old_name"]:
        message = "Party renamed: %s are now '%s'" % (party["old_name"], party["name"])
    else:
        message = "New party started: " + party["name"]

    if party["descriptions"]:
        message += "\n\nAKA:"

        for description in party["descriptions"]:
            new_message = message + '\n• "%s"' % description
            if len(new_message) < 220:
                message = new_message

    auth.set_access_token(data["token"][0], data["token"][1])
    api = tweepy.API(auth)

    media_ids = []
    for image in party["emblems"][:4]:
        response = requests.get(image["url"])

        source = Image.open(io.BytesIO(response.content)).convert("RGBA")

        # If source is smaller than 150px, pad it out to 150
        min_size = 200
        if source.size[0] < min_size or source.size[1] < min_size:
            new_w = max([source.size[0], min_size])
            new_h = max([source.size[1], min_size])
            new_im = Image.new("RGBA", (new_w, new_h))
            new_im.paste(
                source, ((new_w - source.size[0]) // 2, (new_h - source.size[1]) // 2)
            )
            source = new_im

        # Replace background with white
        background = Image.new("RGBA", source.size, (255, 255, 255))
        alpha_composite = Image.alpha_composite(background, source).convert("RGB")
        output = io.BytesIO()
        alpha_composite.save(output, "JPEG", quality=100)

        upload = api.media_upload(
            image["url"].split("/")[-1].split("?")[0], file=output
        )
        media_ids.append(upload.media_id)
        if image["description"]:
            api.create_media_metadata(upload.media_id, image["description"])

    api.update_status(message, media_ids=media_ids)

    print('Tweeted "%s"' % message)
    sys.exit(0)
