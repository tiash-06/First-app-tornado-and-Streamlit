import asyncio
import tornado
from tornado.httpclient import AsyncHTTPClient
from tornado import gen

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, world avec Tornado !")

# Exemple de fonction asynchrone avec le module gen (compatibilité)
@gen.coroutine
def async_fetch_gen(url):
    http_client = AsyncHTTPClient()
    response = yield http_client.fetch(url)
    raise gen.Return(response.body)

def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
    ])

async def main():
    app = make_app()
    app.listen(8888)
    print("Serveur Tornado démarré sur http://localhost:8888")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())