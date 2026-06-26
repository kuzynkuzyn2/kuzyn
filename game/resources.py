"""
Wszystko co związane z zasobami trafia tutaj
"""
import logging
import re
import time

from core.extractors import Extractor


class PremiumExchange:
    """
    Logika interakcji z wymianą premium zasobów
    """

    def __init__(self, wrapper, stock: dict, capacity: dict, tax: dict, constants: dict, duration: int, merchants: int):
        self.wrapper = wrapper
        self.stock = stock
        self.capacity = capacity
        self.tax = tax
        self.constants = constants
        self.duration = duration
        self.merchants = merchants

    # nie nazywaj tego anihilacją (calculate_cost) - odszyfrowałem to z kodu JS TribalWars
    def calculate_cost(self, item, a):
        """
        Obliczenie kosztu giełdy zapasów
        """
        t = self.stock[item]
        n = self.capacity[item]

        # tax = self.tax["buy"] if a >= 0 else self.tax["sell"]
        tax = self.tax["sell"]  # twb never buys on premium exchange

        return (1 + tax) * (self.calculate_marginal_price(t, n) + self.calculate_marginal_price(t - a, n)) * a / 2

    def calculate_marginal_price(self, e, a):
        """
        Matematyczna magia
        """
        c = self.constants
        return c["resource_base_price"] - c["resource_price_elasticity"] * e / (a + c["stock_size_modifier"])

    def calculate_rate_for_one_point(self, item: str):
        """
        Matematyczna magia
        """
        a = self.stock[item]
        t = self.capacity[item]
        n = self.calculate_marginal_price(a, t)
        r = int(1 / n)
        c = self.calculate_cost(item, r)
        i = 0

        while c > 1 and i < 50:
            r -= 1
            i += 1
            c = self.calculate_cost(item, r)

        return r

    @staticmethod
    def optimize_n(amount, sell_price, merchants, size=1000):
        """
        Math magic
        """
        def _ratio(a, b, size=1000):
            a = (size * b) - a
            return a / size

        offers = []

        for i in range(1, merchants + 1):
            for j in range(amount // sell_price + 1):
                r = _ratio(j * sell_price, i, size=size)
                if r >= 0:
                    offers.append((i, r, j))

        offers.sort(key=lambda x: (x[1], -x[0]))

        r = {
            "merchants": offers[0][0],
            "ratio": offers[0][1],
            "n_to_sell": offers[0][2]
        }

        return r


class ResourceManager:
    """
    Klasa do obliczania, przechowywania i rezerwowania zasobów dla akcji
    """
    actual = {}

    requested = {}

    storage = 0
    ratio = 2.5
    max_trade_amount = 4000
    logger = None
    # nie wolno stronniczości
    trade_bias = 1
    last_trade = 0
    trade_max_per_hour = 1
    trade_max_duration = 2
    wrapper = None
    village_id = None
    do_premium_trade = False

    def __init__(self, wrapper=None, village_id=None):
        """
        Tworzy menedżera zasobów
        Preferowany do użycia przez wszystko, co buduje/rekrutuje/wysyła/cokolwiek
        """
        self.wrapper = wrapper
        self.village_id = village_id

    def update(self, game_state):
        """
        Aktualizuje bieżące zasoby na podstawie stanu gry
        """
        self.actual["wood"] = game_state["village"]["wood"]
        self.actual["stone"] = game_state["village"]["stone"]
        self.actual["iron"] = game_state["village"]["iron"]
        self.actual["pop"] = (
                game_state["village"]["pop_max"] - game_state["village"]["pop"]
        )
        self.storage = game_state["village"]["storage_max"]
        self.check_state()
        store_state = game_state["village"]["name"]
        self.logger = logging.getLogger(f"Menedżer zasobów: {store_state}")

    def do_premium_stuff(self):
        """
        Wykonuje operacje premium
        """
        gpl = self.get_plenty_off()
        self.logger.debug(
            "Próba wymiany premium: gpl %s zrobić? %s", gpl, self.do_premium_trade
        )
        if gpl and self.do_premium_trade:
            url = f"game.php?village={self.village_id}&screen=market&mode=exchange"
            res = self.wrapper.get_url(url=url)
            data = Extractor.premium_data(res.text)

            premium_exchange = PremiumExchange(
                wrapper=self.wrapper,
                stock=data["stock"],
                capacity=data["capacity"],
                tax=data["tax"],
                constants=data["constants"],
                duration=data["duration"],
                merchants=data["merchants"]
            )

            cost_per_point = premium_exchange.calculate_rate_for_one_point(gpl)

            self.logger.debug("Koszt za punkt: %s", cost_per_point)
            self.logger.info("Aktualna cena %s: ", self.actual[gpl])

            if not data:
                self.logger.warning("Błąd odczytu danych premium!")
            price_fetch = ["wood", "stone", "iron"]
            prices = {}

            for p in price_fetch:
                prices[p] = data["stock"][p] * data["rates"][p]

            self.logger.info("Aktualne ceny premium: %s",  prices)

            if gpl in prices and prices[gpl] * 1.1 < self.actual[gpl]:
                self.logger.info(
                    "Próba wymiany %d %s na punkt premium", prices[gpl], gpl
                )

                if data["merchants"] < 1:
                    self.logger.info("Za mało kupców!")
                    return

                self.logger.debug(f"Próba wymiany {gpl} - exchange_begin")

                prices[gpl] = int(prices[gpl])

                gpl_data = PremiumExchange.optimize_n(
                    amount=prices[gpl],
                    sell_price=cost_per_point,
                    merchants=data["merchants"],
                    size=1000
                )

                self.logger.debug(f"Zoptymalizowana wymiana: {gpl} {gpl_data} {gpl_data['n_to_sell'] * cost_per_point}")

                if gpl_data["ratio"] > 0.4:
                    self.logger.info("Nie warto handlować!")
                    return

                result = self.wrapper.get_api_action(
                    self.village_id,
                    action="exchange_begin",
                    params={"screen": "market"},
                    data={f"sell_{gpl}": (gpl_data["n_to_sell"] * cost_per_point)},
                )

                if result:
                    _rate_hash = result["response"][0]["rate_hash"]

                    trade_data = {
                        "sell_%s" % gpl: (gpl_data["n_to_sell"] * cost_per_point),
                        "rate_hash": _rate_hash,
                        "mb": "1"
                    }

                    result = self.wrapper.get_api_action(
                        self.village_id,
                        action="exchange_confirm",
                        params={"screen": "market"},
                        data=trade_data,
                    )

                    if result:
                        self.logger.info("Wymiana zakończona pomyślnie!")
                    else:
                        self.logger.info("Wymiana nie powiodła się!")
                else:
                    self.logger.debug(
                        f"Próba wymiany %s na punkty premium - exchange_begin - nie powiodła się", gpl
                    )
                    self.logger.info("Wymiana nie powiodła się!")

    def check_state(self):
        """
        Usuwa żądania zasobów, gdy ilość jest spełniona
        """
        for source in self.requested:
            for res in self.requested[source]:
                if self.requested[source][res] <= self.actual[res]:
                    self.requested[source][res] = 0

    def request(self, source="building", resource="wood", amount=1):
        """
        Po wywołaniu zasoby mogą być pobrane z innych akcji

        """
        if source in self.requested:
            self.requested[source][resource] = amount
        else:
            self.requested[source] = {resource: amount}

    def can_recruit(self):
        """
        Sprawdza, czy populacja jest wystarczająca do rekrutacji
        """
        if self.actual["pop"] == 0:
            self.logger.info("Nie można rekrutować, brak miejsca na populację!")
            for x in self.requested:
                if "recruitment" in x:
                    del self.requested[x]
            return False

        for x in self.requested:
            if "recruitment" in x:
                continue
            types = self.requested[x]
            for sub in types:
                if types[sub] > 0:
                    return False
        return True

    def get_plenty_off(self):
        """
        Sprawdza, czy we wsi jest nadwyżka zasobów
        """
        most_of = 0
        most = None
        for sub in self.actual:
            f = 1
            for sr in self.requested:
                if sub in self.requested[sr] and self.requested[sr][sub] > 0:
                    f = 0
            if not f:
                continue
            if sub == "pop":
                continue
            # self.logger.debug(f"Mamy {self.actual[sub]} {sub}. Wystarczająco? {self.actual[sub]} > {int(self.storage / self.ratio)}")
            if self.actual[sub] > int(self.storage / self.ratio):
                if self.actual[sub] > most_of:
                    most = sub
                    most_of = self.actual[sub]
        if most:
            self.logger.debug(f"Mamy pod dostatkiem {most}")

        return most

    def in_need_of(self, obj_type):
        """
        Sprawdza, czy we wsi brakuje danego zasobu
        """
        for x in self.requested:
            types = self.requested[x]
            if obj_type in types and self.requested[x][obj_type] > 0:
                return True
        return False

    def in_need_amount(self, obj_type):
        """
        Sprawdza, co byłoby potrzebne do spełnienia wymagań
        """
        amount = 0
        for x in self.requested:
            types = self.requested[x]
            if obj_type in types and self.requested[x][obj_type] > 0:
                amount += self.requested[x][obj_type]
        return amount

    def get_needs(self):
        """
        Wszystko powyżej
        """
        needed_the_most = None
        needed_amount = 0
        for x in self.requested:
            types = self.requested[x]
            for obj_type in types:
                if (
                        self.requested[x][obj_type] > 0
                        and self.requested[x][obj_type] > needed_amount
                ):
                    needed_amount = self.requested[x][obj_type]
                    needed_the_most = obj_type
        if needed_the_most:
            return needed_the_most, needed_amount
        return None

    def trade(self, me_item, me_amount, get_item, get_amount):
        """
        Tworzy nową ofertę handlową
        """
        url = f"game.php?village={self.village_id}&screen=market&mode=own_offer"
        res = self.wrapper.get_url(url=url)
        if 'market_merchant_available_count">0' in res.text:
            self.logger.debug("Brak wymiany, ponieważ za mało kupców")
            return False
        payload = {
            "res_sell": me_item,
            "sell": me_amount,
            "res_buy": get_item,
            "buy": get_amount,
            "max_time": self.trade_max_duration,
            "multi": 1,
            "h": self.wrapper.last_h,
        }
        post_url = f"game.php?village={self.village_id}&screen=market&mode=own_offer&action=new_offer"
        self.wrapper.post_url(post_url, data=payload)
        self.last_trade = int(time.time())
        return True

    def drop_existing_trades(self):
        """
        Usuwa istniejącą wymianę, jeśli zasoby są potrzebne gdzie indziej lub wygasła
        """
        url = f"game.php?village={self.village_id}&screen=market&mode=all_own_offer"
        data = self.wrapper.get_url(url)
        existing = re.findall(r'data-id="(\d+)".+?data-village="(\d+)"', data.text)
        for entry in existing:
            offer, village = entry
            if village == str(self.village_id):
                post_url = f"game.php?village={self.village_id}&screen=market&mode=all_own_offer&action=delete_offers"
                post = {
                    "id_%s" % offer: "on",
                    "delete": "Verwijderen",
                    "h": self.wrapper.last_h,
                }
                self.wrapper.post_url(url=post_url, data=post)
                self.logger.info(
                    "Usuwanie oferty %s z rynku, ponieważ istniała zbyt długo" % offer
                )

    def readable_ts(self, seconds):
        """
        Czytelny dla człowieka znacznik czasu
        """
        seconds -= int(time.time())
        seconds = seconds % (24 * 3600)
        hour = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60

        return "%d:%02d:%02d" % (hour, minutes, seconds)

    def manage_market(self, drop_existing=True):
        """
        Zarządza rynkiem za Ciebie
        """
        last = self.last_trade + int(3600 * self.trade_max_per_hour)
        if last > int(time.time()):
            rts = self.readable_ts(last)
            self.logger.debug(f"Nie będę handlował przez {rts}")
            return

        get_h = time.localtime().tm_hour
        if get_h in range(0, 6) or get_h == 23:
            self.logger.debug("Brak zarządzania wymianami między 23-6")
            return
        if drop_existing:
            self.drop_existing_trades()

        plenty = self.get_plenty_off()
        if plenty and not self.in_need_of(plenty):
            need = self.get_needs()
            if need:
                # sprawdź nadchodzące zasoby
                url = f"game.php?village={self.village_id}&screen=market&mode=other_offer"
                res = self.wrapper.get_url(url=url)
                p = re.compile(
                    r"Aankomend:\s.+\"icon header (.+?)\".+?<\/span>(.+) ", re.M
                )
                incoming = p.findall(res.text)
                resource_incoming = {}
                if incoming:
                    resource_incoming[incoming[0][0].strip()] = int(
                        "".join([s for s in incoming[0][1] if s.isdigit()])
                    )
                    self.logger.info(
                        f"Nadchodzą zasoby! %s", resource_incoming
                    )

                item, how_many = need
                how_many = round(how_many, -1)
                if item in resource_incoming and resource_incoming[item] >= how_many:
                    self.logger.info(
                        f"Potrzebny {item} już nadchodzi! ({resource_incoming[item]} >= {how_many})"
                    )
                    return
                if how_many < 250:
                    return

                self.logger.debug("Sprawdzanie bieżących ofert rynkowych")
                if self.check_other_offers(item, how_many, plenty):
                    self.logger.debug("Skorzystano z oferty rynkowej!")
                    return

                if how_many > self.max_trade_amount:
                    how_many = self.max_trade_amount
                    self.logger.debug(
                        "Zmniejszanie ilości wymiany z %d do %d z powodu ograniczenia", how_many, self.max_trade_amount
                    )
                biased = int(how_many * self.trade_bias)
                if self.actual[plenty] < biased:
                    self.logger.debug("Nie można handlować z powodu niewystarczających zasobów")
                    return
                self.logger.info(
                    "Dodawanie wymiany rynkowej %d %s -> %d %s", how_many, item, biased, plenty
                )
                self.wrapper.reporter.report(
                    self.village_id,
                    "TWB_MARKET",
                    "Dodawanie wymiany rynkowej %d %s -> %d %s"
                    % (how_many, item, biased, plenty),
                )

                self.trade(plenty, biased, item, how_many)

    def check_other_offers(self, item, how_many, sell):
        """
        Sprawdza, czy istnieją oferty pasujące do naszych potrzeb
        """
        url = f"game.php?village={self.village_id}&screen=market&mode=other_offer"
        res = self.wrapper.get_url(url=url)
        p = re.compile(
            r"(?:<!-- insert the offer -->\n+)\s+<tr>(.*?)<\/tr>", re.S | re.M
        )
        cur_off_tds = p.findall(res.text)
        p = re.compile(r"Aankomend:\s.+\"icon header (.+?)\".+?<\/span>(.+) ", re.M)
        incoming = p.findall(res.text)
        resource_incoming = {}
        if incoming:
            resource_incoming[incoming[0][0].strip()] = int(
                "".join([s for s in incoming[0][1] if s.isdigit()])
            )

        if item in resource_incoming:
            how_many = how_many - resource_incoming[item]
            if how_many < 1:
                self.logger.info("Żądany zasób już nadchodzi!")
                return False

        willing_to_sell = self.actual[sell] - self.in_need_amount(sell)
        self.logger.debug(
            f"Znaleziono {len(cur_off_tds)} ofert na rynku, chcę sprzedać {willing_to_sell} {sell}"
        )

        for tds in cur_off_tds:
            res_offer = re.findall(
                r"<span class=\"icon header (.+?)\".+?>(.+?)</td>", tds
            )
            off_id = re.findall(
                r"<input type=\"hidden\" name=\"id\" value=\"(\d+)", tds
            )

            if len(off_id) < 1:
                # Za mało zasobów do handlu
                continue

            offer = self.parse_res_offer(res_offer, off_id[0])
            if (
                    offer["offered"] == item
                    and offer["offer_amount"] >= how_many
                    and offer["wanted"] == sell
                    and offer["wanted_amount"] <= willing_to_sell
            ):
                self.logger.info(
                    f"Dobra oferta: {offer['offer_amount']} {offer['offered']} za {offer['wanted_amount']} {offer['wanted']}"
                )
                # Weź ofertę!
                payload = {
                    "count": 1,
                    "id": offer["id"],
                    "h": self.wrapper.last_h,
                }
                post_url = f"game.php?village={self.village_id}&screen=market&mode=other_offer&action=accept_multi&start=0&id={offer['id']}&h={self.wrapper.last_h}"
                # print(f"Wysłano by: {post_url} {payload}")
                self.wrapper.post_url(post_url, data=payload)
                self.last_trade = int(time.time())
                self.actual[offer["wanted"]] = (
                        self.actual[offer["wanted"]] - offer["wanted_amount"]
                )
                return True

        # Nie znaleziono przydatnych ofert
        return False

    def parse_res_offer(self, res_offer, id):
        """
        Analizuje ofertę
        """
        off, want, ratio = res_offer
        res_offer, res_offer_amount = off
        res_wanted, res_wanted_amount = want

        return {
            "id": id,
            "offered": res_offer,
            "offer_amount": int("".join([s for s in res_offer_amount if s.isdigit()])),
            "wanted": res_wanted,
            "wanted_amount": int(
                "".join([s for s in res_wanted_amount if s.isdigit()])
            ),
        }
