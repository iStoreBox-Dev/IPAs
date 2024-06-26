import argparse
import json
import os
from io import StringIO
import requests
import mistletoe
import pandas as pd
from bs4 import BeautifulSoup
from github import Github
import http.client

from get_bundle_id import get_single_bundle_id


def transform_object(original_object):
    transformed_object = {**original_object, "apps": None}

    app_map = {}

    for app in original_object["apps"]:
        (
            name,
            bundle_identifier,
            version,
            version_date,
            size,
            download_url,
            developer_name,
            localized_description,
            icon_url,
        ) = (
            app["name"],
            app["bundleIdentifier"],
            app["version"],
            app["versionDate"],
            app["size"],
            app["downloadURL"],
            app["developerName"],
            app["localizedDescription"],
            app["iconURL"],
        )

        if name not in app_map:
            app_map[name] = {
                "name": name,
                "bundleIdentifier": bundle_identifier,
                "developerName": developer_name,
                "iconURL": icon_url,
                "versions": [],
            }

        app_map[name]["versions"].append(
            {
                "version": version,
                "date": version_date,
                "size": size,
                "downloadURL": download_url,
                "localizedDescription": localized_description,
            }
        )

    for name, app_info in app_map.items():
        app_info["versions"].sort(key=lambda x: x["date"], reverse=True)

    transformed_object["apps"] = list(app_map.values())

    return transformed_object


def download_icon(url, path):
    response = requests.get(url)
    if response.status_code == 200:
        with open(path, 'wb') as f:
            f.write(response.content)
        return True
    return False


def search_for_icon(app_name, developer_name, api_key):
    conn = http.client.HTTPSConnection("google.serper.dev")
    payload = json.dumps({"q": f"{app_name} {developer_name} icon"})
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }
    conn.request("POST", "/images", payload, headers)
    res = conn.getresponse()
    data = res.read()
    result = json.loads(data.decode("utf-8"))

    if "images" in result and len(result["images"]) > 0:
        first_image = result["images"][0]
        if "url" in first_image:
            return first_image["url"]
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--token", help="GitHub token")
    parser.add_argument("-a", "--api_key", help="API key for image search")
    args = parser.parse_args()
    token = args.token
    api_key = args.api_key

    with open("apps.json", "r") as f:
        data = json.load(f)

    if os.path.exists("bundleId.csv"):
        df = pd.read_csv("bundleId.csv")
    else:
        df = pd.DataFrame(columns=["name", "bundleId"])

    md_df = None
    if os.path.exists("README.md"):
        with open("README.md", "r", encoding="utf-8") as f:
            raw_md = f.read()
        html = mistletoe.markdown(raw_md)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if len(tables) > 1:
            table = tables[1]
            md_df = pd.read_html(StringIO(str(table)), keep_default_na=False)[0]
            md_df["App Name"] = md_df["App Name"].str.replace(" ", "").str.lower()
        else:
            print("Expected table not found in README.md")

    # clear apps
    data["apps"] = []

    g = Github(token)
    repo = g.get_repo("swaggyP36000/TrollStore-IPAs")
    releases = repo.get_releases()

    if not os.path.exists("icons"):
        os.makedirs("icons")

    for release in releases:
        print(release.title)

        for asset in release.get_assets():
            if asset.name[-3:] != "ipa":
                continue
            name = asset.name[:-4]
            date = asset.created_at.strftime("%Y-%m-%d")
            try:
                app_name, version = name.split("-", 1)
            except:
                app_name = name
                version = "1.0"

            if app_name in df.name.values:
                bundle_id = str(df[df.name == app_name].bundleId.values[0])
            else:
                bundle_id = get_single_bundle_id(asset.browser_download_url)
                df = pd.concat([df, pd.DataFrame({"name": [app_name], "bundleId": [bundle_id]})], ignore_index=True)

            desc = ""
            dev_name = ""
            if md_df is not None:
                row = md_df.loc[md_df["App Name"] == app_name.replace(" ", "").lower()]
                if len(row.values):
                    raw_desc = row["Description"].values[0]
                    raw_last_updated = row["Last Updated"].values[0]
                    raw_status = row["Status"].values[0]
                    desc = f"{raw_desc}\nLast updated: {raw_last_updated}\nStatus: {raw_status}"
                    dev_name = f"{row['Source/Maintainer'].values[0]}"

            icon_url = f"https://raw.githubusercontent.com/iStoreBox-Dev/IPAs/main/icons/{bundle_id}.png"
            icon_path = os.path.join("icons", f"{bundle_id}.png")
            if not download_icon(icon_url, icon_path):
                search_icon_url = search_for_icon(app_name, dev_name, api_key)
                if search_icon_url:
                    if download_icon(search_icon_url, icon_path):
                        icon_url = search_icon_url
                    else:
                        print(f"Failed to download searched icon for {app_name}")
                else:
                    print(f"Icon not found for {app_name}")

            data["apps"].append(
                {
                    "name": app_name,
                    "bundleIdentifier": bundle_id,
                    "version": version,
                    "versionDate": date,
                    "size": asset.size,
                    "downloadURL": asset.browser_download_url,
                    "developerName": dev_name,
                    "localizedDescription": desc,
                    "iconURL": icon_url,
                }
            )

    df.to_csv("bundleId.csv", index=False)

    with open("apps_esign.json", "w") as json_file:
        json.dump(data, json_file, indent=2)

    with open("apps.json", "w") as file:
        json.dump(transform_object(data), file, indent=2)
