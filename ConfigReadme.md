

# Podręcznik konfiguracji
Plik pomocy do definiowania niestandardowego pliku konfiguracyjnego.
## Serwer
**Nazwa użytkownika i hasło** 
Od wersji 1.2 nie jest to już wymagane, ponieważ login jest chroniony przez captchę

**Endpoint & Serwer & Świat**
To są pierwsze części URL, na którym gra TW się znajduje. Endpoint powinien zaczynać się od "https://" i kończyć się na "game.php". Serwer i świat to serwer, na którym aktualnie grasz, w większości przypadków (jeśli nie we wszystkich) to pierwsza część URL-a endpoint-a po "https://".

**Ma Recaptchę**
To nie ma nic wspólnego z ochroną botów w grze, po prostu mówi skryptowi, że standardowa procedura logowania powinna być pominięta i zamiast tego poprosić o ciąg ciastek.

**Serwer na TWPlus**
Jeśli twój świat gry nie jest (jeszcze) dostępny na [http://twplus.org/](http://twplus.org/) ustaw na false. To automatycznie pobierze dane związane ze światem, takie jak populacja wymagana dla niektórych budynków.

## Zdalny login
Bot ma funkcję do zdalnego logowania przy użyciu MySQL i plików.
Domyślnie każdy start (uruchomienie twb.py) tworzy nowy plik dziennika na podstawie bieżącego znacznika czasu.
Jeśli chcesz, aby bot logował się do MySQL, wymagane jest dostarczenie ciągu połączenia w taki sposób:
`mysql://username:password@hostname:3306/database_name`
Powinien automatycznie utworzyć wymagane tabele, jeśli jeszcze nie istnieją.

## Bot
To będzie konfigurować funkcje niezwiązane z grą.

**Godziny aktywności**
Godziny, w których bot powinien być aktywny, domyślnie od 6 rano do 23 w nocy. Bieżący czas zostanie ustawiony na Twoją bieżącą strefę czasową, więc jeśli Twoja strefa czasowa różni się od strefy gry, upewnij się, że uwzględniasz różnicę w czasie!

**Opóźnienie aktywne, opóźnienie nieaktywne i nieaktywne, ale wciąż aktywne**
Opóźnienie aktywne konfiguruje minimalny czas, jaki bot czeka do następnego uruchomienia podczas godzin aktywności. Opóźnienie nieaktywne będzie konfigurować to samo dla godzin nieaktywności. Jeśli inactive_still_active jest wyłączone, bot całkowicie wyłączy się podczas godzin nieaktywności i prawdopodobnie przesunie Twoją sesję, musisz ręcznie ponownie uruchomić bota rano.

**Wymuszone czasy pokoju**
Tablica razy, w których nie możesz atakować (Boże Narodzenie itp..). Powinno być w postaci:
```
[{"start:": "%d.%m.%y %H:%M:%S", "end":"%d.%m.%y %H:%M:%S"}, {"start:": "24.12.2001 17:00:00", "end":"27.12.2001 01:00:00"}]
```

## Budynek
Wartość logiczna manage_building może wyłączyć budowanie globalnie, więc nie będziesz musiał ręcznie ponownie konfigurować wszystkich swoich wsi.
**Domyślnie** 
ustawi domyślny szablon budynku, osobiście lubię ten purple_predator, ale niestandardowe można dostarczyć w folderze szablonów konstruktora.

**Maksimum spoglądania w przód**
Maksymalna liczba budynków w kolejce, które są sprawdzane, jeśli te przed nimi się nie powiodą (np. niewystarczające zasoby lub wymagania nie są jeszcze spełnione). Sugeruję utrzymywać tę liczbę poniżej 5, ponieważ w innym przypadku najprawdopodobniej kolejkuje najpierw najtańsze budynki.

**Maksymalna liczba pozycji w kolejce**
Liczba przedmiotów, które mogą być jednocześnie w kolejce, domyślnie: 2. Konta premium mogą mieć więcej, ale nie polecam.

## Jednostki
Ta sekcja będzie konfigurować sposób szkolenia jednostek. Po włączeniu opcji rekrutacji wsie powinny automatycznie zacząć produkować jednostki po ukończeniu koszar. Domyślnie będzie utworzonych tylko kilka jednostek na początek procedury farmy, aż koszary osiągną wyższy poziom.

Szablony jednostek można konfigurować w folderze szablonu oddziałów. Jednostki są konfigurowane od góry do dołu, a wybrana zostanie najniższa z wymaganiami budynku spełnionymi jako bieżący szablon jednostek.

Bieżący szablon wskazuje również, ile i jakie jednostki farmy powinny być używane przez sekcję farmy.

**Aktualizacja**
Domyślnie, gdy „uaktualnienie" jest włączone, skrypt będzie automatycznie badać jednostki wymienione w bieżącym szablonie. Ta część obsługuje oba systemy uaktualniania i będzie automatycznie badać wszystko (poziom 0-1, 0-3, 0-10), jeśli jest wystarczająco dużo czasu i zasobów. Wyższe aktualizacje na poziomie mogą zająć chwilę, ponieważ większość zasobów zostanie wydana przez konstruktora i rekrutera.

**Rozmiar partii**
Liczba jednostek, które będzie próbować rekrutować w jednorazowo, gdy wejdziesz w fazę końcową gry (poziom koszar 25+) sugeruję ustawić to na coś w zakresie 500-1500. Utrzymanie go na niskim poziomie pozwoli na większą zmienność, co jest przydatne na początkach na świecie.
Uwaga: rozmiar partii będzie zawsze maksymalną liczbą jednostek w jednej próbie, jeśli niewystarczające zasoby, skrypt obliczy najniższą możliwą liczbę jednostek.

## Auto Farm Assistant

Ta sekcja zawiera ustawienia nowego `farm_assistant`, które zastępuje starą sekcję konfiguracyjną dotyczącą farmowania.
Umożliwia skonfigurowanie automatycznych ataków wykonywanych przez Farm Assistant (widok gry kończący się na `&screen=am_farm`).

Główne parametry dostępne w `farm_assistant`:

Uwaga: automatyczne wysyłanie ataków zwiększa ryzyko wykrycia i bana — ustawiaj przerwy i opcje ostrożnie.

## Targ
Funkcja targu automatycznie zarządza zasobami w Twojej wiosce. Jest to szczególnie ładnie, gdy konstruktor ma mało określonego zasobu i ma wiele innych.
"max_trade_duration" konfiguruje maksymalną ilość czasu handlu w godzinach, powinno to być utrzymywane na niskim poziomie.

**Częstotliwość handlowania**
Handlowiec będzie automatycznie usuwać wszystkie przedmioty wymienione więcej niż "max_trade_duration" w godzinach. Gdy również dokonujesz niestandardowego handlu z wioską, sugeruję wyłączenie opcji "auto_remove".

**Mnożnik handlowy**
Jeśli Twój świat nie pozwala na nierówny handel, powinieneś wyłączyć opcję "trade_multiplier". Domyślnie jest włączona przy współczynniku 0,9, więc będzie handlować 900 kamieniami za 1000 drewna, jeśli 1000 to żądany zasób przez konstruktora.
Sugeruję utrzymywać mnożnik współczynnika poniżej 1,0, ponieważ w innym przypadku płacisz więcej niż powinieneś ;)

## Opcje świata
Myślę, że tylko "quests_enabled" aktualnie działa i powinien automatycznie ukończyć zadania, gdy spełnione zostaną wszystkie wymagania. Gdy tak się stanie, powinien ponownie uruchomić bieżący przebieg dla wsi, ponieważ może być nagroda za zasoby powiązana z misją.

# Konfiguracja wsi
To konfiguruje co i jak wsie są zarządzane. Zarówno budynek, jak i jednostki zastępują globalne opcje szablonu. Jeśli chcesz, aby bot (tymczasowo) pominął wioskę, możesz wyłączyć opcję "managed".

**Priorytet budynku**
Zawsze, gdy "prioritize_building" jest włączone, rekruter będzie tworzyć tylko jednostki, gdy przedmioty budynku w kolejce równają się wartości "max_queued_items" ustawionej w konfiguracji budynku.

**Priorytet szlachty**
To zmusi bota do zarezerwowania zasobów do tworzenia szlachty, tylko konstruktor ma wyższy priorytet. Będzie również żądać zasobów z targu do tworzenia monet i tworzenia szlachty.
Liczbę szlachty, którą można stworzyć w wiosce, można skonfigurować za pomocą parametru "snobs".

**Farmy niestandardowe**
Ta sekcja zawiera ustawienia nowego `farm_assistant`, które zastępuje starą sekcję konfiguracyjną dotyczącą farmowania.
*Uwaga: Ta opcja może być bardzo niebezpieczna! jeśli wioskę przejmiesz ty lub inny gracz, bot będzie nadal atakować, aż do śmierci wojsk lub wyłączenia wpisu w pliku pamięci wsi.*

**Zbieranie**
Jeśli wojska nie są używane do farmy i nie ma ataku przychodzącego, wieś będzie automatycznie próbować rozpocząć operację zbierania.
Możesz włączyć/wyłączyć to za pomocą parametru gather i ustawić domyślną operację zbierania za pomocą opcji "gather_selection".