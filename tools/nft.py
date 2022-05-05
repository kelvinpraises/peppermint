#!/usr/bin/env python3

import sys
import base58
import json
import psycopg2
import requests


config = {}

# async def persist_nfts(nfts):
#     for nft in nfts:
#         nft_id = nft['id']
#         with open(os.path.join('nfts', f'{nft_id}.json'), 'w') as fp:
#             fp.write(json.dumps(nft))


# class ImageException(Exception):
#     """
#     Raised when image acquisition failed
#     """

#     def __init__(self, message='Image acquisition failed'):
#         self.message = message
#         super().__init__(self.message)


class IpfsException(Exception):
    """
    Raised when upload to Pinata failed
    """

    def __init__(self, message='Ipfs failed'):
        self.message = message
        super().__init__(self.message)


def connect_db():
    return psycopg2.connect(
        host=config['DB_HOST'],
        database=config['DB_NAME'],
        user=config['DB_USER'],
        password=config['DB_PASSWORD'])


def queue_create_op(content_ipfs_hash, token_id, handler, originator):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO peppermint.operations(originator, command) VALUES (%s, %s);",
                (originator,
                 json.dumps({
                     "handler": handler,
                     "name": "create_token",
                     "args": {
                         "token_id": token_id,
                         "metadata_ipfs": f"ipfs://{content_ipfs_hash}",
                     }
                 })))
    conn.commit()
    conn.close()


def get_token_id(ipfs):
    b = base58.b58decode(ipfs)
    token_id = int.from_bytes(b[-6:], 'big')
    return token_id


def get_uri_from_hash(hash):
    return f"ipfs://{hash}"


def get_nft_metadata(ipfs_hashes, nft):
    metadata = {
        "name": nft['name'],
        "description": nft['description'],
#        "tags": [],
        "symbol": nft['symbol'],
        "artifactUri": get_uri_from_hash(ipfs_hashes['artifact']),
        "displayUri": get_uri_from_hash(ipfs_hashes['display']),
        "thumbnailUri": get_uri_from_hash(ipfs_hashes['thumbnail']),
#        "creators": [],
        "formats": [
            {
                "uri": get_uri_from_hash(ipfs_hashes['artifact']),
                "mimeType": "image/jpeg"
            }
        ],
        "decimals": 0,
        "isTransferable": True,
        "isBooleanAmount": nft['is_boolean']
    }
    return metadata


def upload_file_to_pinata(filename):
    headers = {"Authorization": f"Bearer {config['PINATA_JWT']}"}
    with open(filename,'rb') as bin:
        response = requests.post("https://api.pinata.cloud/pinning/pinFileToIPFS",
                                headers=headers,
                                files={'file': bin},
                                )
    if response.status_code != 200:
        raise IpfsException
    return json.loads(response.content)


def upload_json_to_pinata(obj):
    headers = {"Authorization": f"Bearer {config['PINATA_JWT']}"}
    response = requests.post("https://api.pinata.cloud/pinning/pinJSONToIPFS",
                             headers=headers,
                             json=obj,
                             )
    if response.status_code != 200:
        raise IpfsException
    return json.loads(response.content)


def upload_assets_to_pinata(nft):
    hashes = {
        "artifact": upload_file_to_pinata(nft['artifact_filename'])['IpfsHash'],
        "display": upload_file_to_pinata(nft['display_filename'])['IpfsHash'],
        "thumbnail": upload_file_to_pinata(nft['thumbnail_filename'])['IpfsHash']
    }
    metadata = get_nft_metadata(hashes, nft)
    metadata_ipfs_hash = upload_json_to_pinata(metadata)['IpfsHash']
    return metadata_ipfs_hash


def create_ipfs_metadata(nft):
    metadata_ipfs_hash = upload_assets_to_pinata(nft)
    print(f"uploaded NFT assets with metadata IPFS hash {metadata_ipfs_hash}")
    nft['metadata_ipfs_hash'] = metadata_ipfs_hash
    return nft


#main

if len(sys.argv) < 3:
    print("Usage: nft.py {command} {filename} [args...]")
    print("Commands: upload_ipfs, create_token")
    exit

with open('config.json') as f:
    config = json.load(f)

filename = sys.argv[2]
command = sys.argv[1]

with open(filename) as f:
    nft = json.load(f)
print(f"processing:\n{json.dumps(nft)}")

if command == 'upload_ipfs':
    nft = upload_assets_to_pinata(nft)
    with open(filename, 'w') as f:
        f.write(json.dumps(nft))
    print(f"IPFS hash persisted into {filename}")
elif command == 'create_token':
    if not nft['metadata_ipfs_hash']:
        print("NFT metadata is not in IPFS yet")
        exit
    if len(sys.argv) < 4:
        print("Usage: nft.py create_token {peppermint handler} [token_id]")
        exit
    peppermint_handler = sys.argv[3]
    if len(sys.argv) > 4:
        token_id = sys.argv[4]
    else:
        token_id = get_token_id(nft['metadata_ipfs_hash'])

    queue_create_op(nft['metadata_ipfs_hash'], token_id, peppermint_handler, config['PEPPERMINT_ORIGINATOR'])
