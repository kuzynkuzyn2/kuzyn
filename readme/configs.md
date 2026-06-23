

# Instrukcja konfiguracji
Plik pomocy do definiowania niestandardowego pliku konfiguracji.
## Serwer
**Nazwa użytkownika i hasło** 
Można je podać do automatycznego logowania, nie jest wymagane, jeśli has_recaptcha jest włączone lub dostarczona jest ciąg pliku cookie.

**Punkt końcowy, serwer i świat**
Są to pierwsze części adresu URL, w którym znajduje się gra TW. Endpoint powinien zaczynać się od "https://" i kończyć się na "game.php". Server i world to serwer, na którym aktualnie grasz, w większości przypadków (jeśli nie wszystkich) jest to pierwsza część adresu URL endpoint po "https://".

**Has Recapcha**
To nie ma nic wspólnego z ochroną przed botami w grze, po prostu mówi skryptowi, że standardowa procedura logowania powinna być pominięta i zamiast tego poproś o ciąg pliku cookie.

**Server on TWPlus**
Jeśli twój świat gry nie jest (jeszcze) dostępny na [http://twplus.org/](http://twplus.org/) ustaw na false. To automatycznie pobierze dane związane ze światem, takie jak populacja wymagana dla określonych budynków.

## Bot
To będzie konfigurować funkcje niezwiązane z grą.
**Aktywne godziny**
Godziny, w których bot powinien być aktywny, domyślnie od 6 rano do 23 w nocy. Bieżący czas będzie ustawiony na twoją bieżącą strefę czasową, dlatego jeśli twoja strefa czasowa różni się od strefy gry, upewnij się, że uwzględniasz różnicę czasu!
**Opóźnienie aktywne, opóźnienie nieaktywne i opóźnienie nieaktywne Wciąż aktywne**
Opóźnienie aktywne konfiguruje minimalny czas, jaki bot będzie czekać do następnego uruchomienia podczas aktywnych godzin. Opóźnienie nieaktywne będzie konfigurować to samo dla godzin nieaktywnych. Jeśli inactive_still_active jest wyłączone, bot całkowicie wyłączy się w godzinach nieaktywnych i prawdopodobnie upłynie limit czasu sesji, więc musisz ręcznie uruchomić ponownie bota rano.

## Powiadomienia
Powiadomienia, gdy włączone, będą wysyłać wiadomości do kanału telegram.

### Konfiguracja
Aby móc wysyłać wiadomości do kanału telegram, musisz najpierw stworzyć bota. Aby to zrobić, możesz rozpocząć rozmowę z [BotFather](https://t.me/botfather) i stworzyć nowego bota (`/newbot`). Po utworzeniu bota otrzymasz token, ten token powinien być dodany do parametru "notifications.token" w pliku konfiguracji.

Po utworzeniu bota będziesz musiał stworzyć kanał i dodać bota jako administratora. Następnie możesz uzyskać identyfikator kanału, wysyłając wiadomość do kanału i przesyłając ją do [JsonDumpBot](https://t.me/JsonDumpBot). `forward_origin.chat.id` powinno być dodane do parametru "notifications.channel_id" w pliku konfiguracji.

Nie zapomnij włączyć parametru "notifications.enabled" w pliku konfiguracji.

## Budynki
Wartość logiczna manage_building może wyłączyć budowanie globalnie, więc nie będziesz musiał ponownie konfigurować wszystkich wsi ręcznie.
**Domyślnie** 
ustawi domyślny szablon budynku, osobiście lubię purple_predator, ale niestandardowe można dostarczyć w folderze szablonów buildera.

**Max Look-ahead**
Maksymalna ilość budynków w kolejce, które są sprawdzane, jeśli te przed nimi nie powiedzie się (takie jak brak wystarczających zasobów lub wymagania nie zostały jeszcze spełnione). Sugeruję, abyś utrzymywał tę liczbę poniżej 5, ponieważ w przeciwnym razie najprawdopodobniej najpierw będzie kolejkować najtańsze budynki.

**Max Queued Items**
Liczba elementów, które mogą być kolejkowane jednocześnie, domyślnie: 2. Konta premium mogą mieć więcej, ale nie polecam tego.

## Jednostki
Ta sekcja będzie konfigurować, jak jednostki powinny być szkolone. Po włączeniu opcji recruit wioski powinny automatycznie zacząć produkować jednostki po zakończeniu budowy koszar. Domyślnie tylko kilka jednostek do uruchomienia procedury farmy będzie utworzonych, dopóki koszary nie osiągną wyższego poziomu.

Szablony jednostek można skonfigurować w folderze szablonów drużyn. Jednostki są konfigurowane od góry do dołu, a najniższy z wymaganiem konstrukcji spełnianym zostanie wybrany jako bieżący szablon jednostki.

Bieżący szablon również wskazuje, ile i jakich jednostek farmy powinno być używanych przez sekcję farmy.

**Ulepszanie**
Domyślnie, gdy "upgrade" jest włączone, skrypt automatycznie zbada jednostki wymienione w bieżącym szablonie. Ta część obsługuje oba systemy ulepszania i automatycznie zbada wszystko (poziom 0-1, 0-3, 0-10), jeśli ma wystarczająco dużo czasu i zasobów. Ulepszenia wyższego poziomu mogą zająć trochę czasu, ponieważ większość zasobów zostanie wydana przez buildera i rekrutera.

**Rozmiar partii**
Ilość jednostek, które będzie próbować zwerbować w jednym momencie, wchodząc w grę w fazie końcowej (poziom koszar 25+), sugeruję ustawienie tego na coś w zakresie 500-1500. Utrzymywanie go nisko pozwoli na większą zmienność, która jest przydatna na początku na świecie.
Uwaga: rozmiar partii zawsze będzie maksymalną ilością jednostek w jednej próbie, jeśli niewystarczające zasoby, skrypt obliczy najniższą możliwą ilość jednostek.

## Auto Farm Assistant

Sekcja `farm_assistant` zastępuje starą konfigurację dotyczącą farmowania i zawiera ustawienia dla automatycznych ataków wykonywanych przez Farm Assistant (widok `&screen=am_farm`).

Najważniejsze ustawienia są opisane w `config.example.json` i obejmują: `enabled`, progi punktów, promień wyszukiwania, czasy oczekiwania między atakami, `max_farms`, `farm_scout_amount`, przycisk asystenta (`farm_assistant_button`), progi murów oraz `auto_send_assistant_attacks`.

Uwaga: automatyczne wysyłanie ataków może zwiększyć ryzyko bana — używaj ostrożnie.

## Targ
Funkcja targu automatycznie zarządza zasobami w twojej wiosce. To jest szczególnie miłe, ilekroć builder jest mały na pewny zasób i ma wiele innych.
"max_trade_duration" konfiguruje maksymalną ilość czasu handlu w godzinach, powinno to być utrzymywane nisko.

**Częstotliwość handlu**
Handlowiec automatycznie usunie wszystkie towary wymienione więcej niż "max_trade_duration" w godzinach. Przy jednoczesnym niestandardowym handlu z wioską sugeruję wyłączenie opcji "auto_remove".

**Mnożnik handlu**
Jeśli twój świat nie pozwala na nierówny handel, powinieneś wyłączyć opcję "trade_multiplier". Domyślnie jest włączone ze współczynnikiem 0,9, dlatego będzie handlować 900 kamieniami za 1000 drewna, jeśli 1000 jest żądanym zasobem przez buildera.
Sugeruję utrzymywać mnożnik współczynnika poniżej 1,0, ponieważ w przeciwnym razie płacisz więcej niż powinieneś ;)

## Opcje świata
Myślę, że tylko "quests_enabled" aktualnie działa i powinno automatycznie zakończyć zadania po spełnieniu wszystkich wymagań. Gdy tak się stanie, powinno ponownie uruchomić bieżący przebieg dla wioski, ponieważ może istnieć nagroda zasobów połączona z zadaniem.

# Konfiguracja wioski
Konfiguruje to, co i jak wioski są zarządzane. Zarówno building, jak i jednostki zastępują globalne opcje szablonu. Jeśli chcesz, aby bot (czasowo) pominął wioskę, możesz wyłączyć opcję "managed".

**Priorytet budynku**
Ilekroć "prioritize_building" jest włączone, rekruter będzie tworzyć jednostki tylko wtedy, gdy elementy budowy w kolejce równają się wartości "max_queued_items" ustawionej w konfiguracji budynku.

**Priorytet szlachty**
To będzie zmuszać bota do zarezerwowania zasobów do tworzenia szlachty, tylko builder ma wyższy priorytet. Będzie również żądać zasobów z targu do tworzenia monet i tworzenia szlachty.
Ilość szlacht, które można stworzyć w wiosce, można skonfigurować parametrem "snobs".

**Farmy niestandardowe**
Każda wieś może mieć listę farmy niestandardowej w parametrze "additional_farms", identyfikatory wioski powinny być dodane jako ciągi. 
*Uwaga: ta opcja może być bardzo niebezpieczna! jeśli wioska zostanie przejęta przez ciebie lub innego gracza, bot będzie nadal atakować, aż żołnierze umrą lub wpis zostanie wyłączony w pliku pamięci podręcznej wioski.*
