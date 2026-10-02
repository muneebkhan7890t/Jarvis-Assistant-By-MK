import json
from core.market_analysis import analyze


def run(parameters, **kwargs):
    return json.dumps(analyze(parameters.get('asset', 'best')), ensure_ascii=False)


TOOL = {'name': 'market_analysis',
        'description': 'READ-ONLY trade-setup analysis. Use when asked for the best setup, analyze crypto, Bitcoin/BTC, Ethereum/ETH, or check gold. Fetches public BTC/ETH daily, 4h, 1h and 15m candles and computes indicators plus conditional watchlists. Gold returns data requirements if no feed exists. Never creates orders. Explain missing checks and never promise returns or invent levels.',
        'parameters': {'type': 'OBJECT', 'properties': {'asset': {'type': 'STRING', 'description': 'best | BTC | ETH | gold'}}, 'required': ['asset']},
        'handler': run}
