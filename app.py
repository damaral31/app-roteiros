import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import uuid
import json
import os
import math
import random
import re 

# --- CONFIGURAÇÃO E CONSTANTES ---
st.set_page_config(page_title="AI Travel Planner", layout="wide", page_icon="🧠")

DATA_FILE = "travel_data.json"
WALKING_SPEED_KMH = 5.0
DRIVING_SPEED_KMH = 35.0  # Velocidade média carro em cidade (para Hotel -> POI)
TOLERANCIA_MINUTOS = 30 

# --- FUNÇÃO DE CONVERSÃO DE COORDENADAS ---
def parse_coordinate(coord_input):
    """Converte inputs variados (DMS string ou Float string) para Float Decimal."""
    coord_str = str(coord_input).strip()
    try:
        return float(coord_str)
    except ValueError:
        pass
    
    regex = r"(\d+)[°º\s]+(\d+)['\s]+([\d.]+)[\"\s]*([NSEWnsew])?"
    match = re.search(regex, coord_str)
    
    if match:
        deg, min, sec, direction = match.groups()
        decimal = float(deg) + (float(min) / 60) + (float(sec) / 3600)
        if direction and direction.upper() in ['S', 'W']:
            decimal *= -1
        return round(decimal, 6)
    return None

# --- FUNÇÃO DE PESQUISA DE LOCAL ---
def search_place_nominatim(query):
    """Pesquisa local usando OpenStreetMap (Gratuito)."""
    try:
        geolocator = Nominatim(user_agent="travel_architect_ai_app_final_v5_addr")
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
        return None, None, None
    except (GeocoderTimedOut, Exception) as e:
        return None, None, str(e)

# --- PERSISTÊNCIA DE DADOS ---
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state['cities'], f, indent=4, ensure_ascii=False)

# --- MOTOR DE OTIMIZAÇÃO (SIMULATED ANNEALING) ---
class TravelOptimizer:
    def __init__(self, pois, hotel, max_h_manha, max_h_tarde):
        self.pois = pois
        self.hotel = hotel
        self.max_min_manha = (max_h_manha * 60) + TOLERANCIA_MINUTOS
        self.max_min_tarde = (max_h_tarde * 60) + TOLERANCIA_MINUTOS
        self.dist_matrix = {}
        self._precompute_distances()

    def _get_dist_time(self, id1, id2):
        return self.dist_matrix.get((id1, id2), 0)

    def _precompute_distances(self):
        all_nodes = self.pois + [self.hotel]
        for p1 in all_nodes:
            for p2 in all_nodes:
                if p1['id'] == p2['id']: continue
                
                # Calcula distancia geodésica em KM
                dist = geodesic((p1['lat'], p1['lon']), (p2['lat'], p2['lon'])).km
                
                # LÓGICA DE VELOCIDADE:
                # Se p1 (origem) for o Hotel, assumimos que vai de Carro/Uber
                if p1.get('type') == 'hotel':
                    speed = DRIVING_SPEED_KMH
                else:
                    # Se p1 for um local turístico, assumimos caminhada até o próximo
                    speed = WALKING_SPEED_KMH
                
                # Calcula tempo em minutos
                self.dist_matrix[(p1['id'], p2['id'])] = int((dist / speed) * 60)

    def _evaluate_schedule(self, ordered_pois):
        schedule = []
        pendentes = ordered_pois.copy()
        total_travel = 0
        visited_count = 0
        dia = 1
        
        while pendentes and dia <= 10:
            # Manhã
            loc_atual = self.hotel
            tempo_gasto = 0
            manha_pois = []
            i = 0
            while i < len(pendentes):
                poi = pendentes[i]
                travel = self._get_dist_time(loc_atual['id'], poi['id'])
                cost = travel + poi['time_min']
                if (tempo_gasto + cost) <= self.max_min_manha:
                    p = poi.copy()
                    p.update({'day': dia, 'period': 'Manhã', 'transit_prev': travel})
                    manha_pois.append(p)
                    tempo_gasto += cost; total_travel += travel; loc_atual = poi; visited_count += 1
                    pendentes.pop(i)
                else: i += 1
            
            # Tarde
            # Se terminou a manhã num POI, continua a pé. Se não teve manhã, sai do hotel (carro).
            loc_atual = manha_pois[-1] if manha_pois else self.hotel
            tempo_gasto = 0
            tarde_pois = []
            i = 0
            while i < len(pendentes):
                poi = pendentes[i]
                travel = self._get_dist_time(loc_atual['id'], poi['id'])
                cost = travel + poi['time_min']
                if (tempo_gasto + cost) <= self.max_min_tarde:
                    p = poi.copy()
                    p.update({'day': dia, 'period': 'Tarde', 'transit_prev': travel})
                    tarde_pois.append(p)
                    tempo_gasto += cost; total_travel += travel; loc_atual = poi; visited_count += 1
                    pendentes.pop(i)
                else: i += 1
            
            if manha_pois or tarde_pois:
                schedule.extend(manha_pois + tarde_pois)
                dia += 1
            else: break
        return schedule, visited_count, total_travel

    def solve_simulated_annealing(self, iterations=3000, temp=1000, cooling_rate=0.995):
        current_solution = self.pois.copy()
        random.shuffle(current_solution)
        current_sched, curr_vis, curr_trav = self._evaluate_schedule(current_solution)
        current_energy = -(curr_vis * 10000) + curr_trav
        
        best_solution = current_solution[:]
        best_energy = current_energy
        best_schedule = current_sched
        
        for i in range(iterations):
            new_solution = current_solution[:]
            idx1, idx2 = random.sample(range(len(new_solution)), 2)
            new_solution[idx1], new_solution[idx2] = new_solution[idx2], new_solution[idx1]
            
            new_sched, new_vis, new_trav = self._evaluate_schedule(new_solution)
            new_energy = -(new_vis * 10000) + new_trav
            
            delta = new_energy - current_energy
            if delta < 0 or random.random() < math.exp(-delta / temp):
                current_solution = new_solution
                current_energy = new_energy
                if new_energy < best_energy:
                    best_energy = new_energy
                    best_schedule = new_sched
            temp *= cooling_rate
            
        final_list = [{'id': self.hotel['id'], 'name': self.hotel['name'], 'lat': self.hotel['lat'], 'lon': self.hotel['lon'], 'type': 'hotel', 'day': 0, 'period': 'Base', 'time_min': 0}]
        final_list.extend(best_schedule)
        
        visited_ids = set(p['id'] for p in best_schedule)
        for p in self.pois:
            if p['id'] not in visited_ids:
                pc = p.copy(); pc.update({'day': 0, 'period': '-'}); final_list.append(pc)
        return final_list

def run_optimization_logic(pois, max_h_manha, max_h_tarde):
    hotel = next((p for p in pois if p.get('type') == 'hotel'), None)
    visit_pois = [p for p in pois if p.get('type') != 'hotel']
    if not hotel: return None, "Defina um Hotel."
    if not visit_pois: return pois, "Adicione locais."
    optimizer = TravelOptimizer(visit_pois, hotel, max_h_manha, max_h_tarde)
    return optimizer.solve_simulated_annealing(), "Otimização concluída!"

# --- UI COMPONENTS ---

def render_dashboard():
    st.title("🌍 AI Travel Planner")
    st.caption("Suporta pesquisa de locais (OSM) e coordenadas decimais.")
    st.markdown("---")

    with st.expander("➕ Adicionar Novo Destino", expanded=False):
        with st.form("new_city_form"):
            c_name = st.text_input("Nome da Cidade")
            c1, c2 = st.columns(2)
            raw_lat = c1.text_input("Latitude", placeholder="Decimal ou DMS")
            raw_lon = c2.text_input("Longitude", placeholder="Decimal ou DMS")
            c_img = st.text_input("URL da Imagem", placeholder="https://...")
            
            if st.form_submit_button("Criar Destino"):
                lat_float = parse_coordinate(raw_lat)
                lon_float = parse_coordinate(raw_lon)

                if c_name and lat_float is not None and lon_float is not None:
                    cid = str(uuid.uuid4())
                    st.session_state['cities'][cid] = {
                        "id": cid, "name": c_name, "lat": lat_float, "lon": lon_float, 
                        "img": c_img if c_img else "https://via.placeholder.com/300x150", "pois": []
                    }
                    save_data()
                    st.success(f"Destino criado em {lat_float}, {lon_float}")
                    st.rerun()
                else:
                    st.error("Erro nas coordenadas ou nome vazio.")

    st.subheader("Meus Destinos")
    if not st.session_state['cities']:
        st.info("Nenhuma cidade adicionada ainda.")
        return

    cols = st.columns(3)
    city_items = list(st.session_state['cities'].items())

    for idx, (cid, city) in enumerate(city_items):
        with cols[idx % 3].container(border=True):
            st.image(city['img'], use_container_width=True)
            st.markdown(f"### {city['name']}")
            col_plan, col_del = st.columns([4, 1])
            with col_plan:
                if st.button(f"Planear", key=f"btn_plan_{cid}", use_container_width=True):
                    st.session_state['selected_city_id'] = cid
                    st.rerun()
            with col_del:
                if st.button("🗑️", key=f"btn_del_{cid}", help="Apagar destino"):
                    del st.session_state['cities'][cid]
                    save_data(); st.toast("Removido!"); st.rerun()

def render_stylish_card(poi, city_id, is_first=False):
    """Renderiza um cartão visualmente rico para o Roteiro."""
    if not is_first and 'transit_prev' in poi and poi['transit_prev'] > 0:
        icon_transit = "🚗" if poi.get('transit_prev') > 45 else "🚶"
        st.markdown(f"""
        <div style="text-align: center; color: #888; font-size: 0.8em; margin: 5px 0;">
            ⋮<br>{icon_transit} <i>{poi['transit_prev']} min deslocamento</i><br>⋮
        </div>
        """, unsafe_allow_html=True)

    with st.container(border=True):
        col_icon, col_info, col_action = st.columns([1, 5, 1])
        with col_icon:
            icon = "🏨" if poi.get('type') == 'hotel' else "📍"
            st.markdown(f"<div style='font-size: 2.5em; text-align: center; padding-top: 10px;'>{icon}</div>", unsafe_allow_html=True)
        
        with col_info:
            st.markdown(f"**{poi['name']}**")
            tags = []
            tags.append(f"⏱️ {poi['time_min']} min")
            if poi.get('cost', 0) > 0: tags.append(f"💶 {poi['cost']}€")
            
            if tags:
                tags_html = "".join([f"<span style='background-color: #f0f2f6; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; margin-right: 5px; color: #444; border: 1px solid #e0e0e0;'>{t}</span>" for t in tags])
                st.markdown(tags_html, unsafe_allow_html=True)
            if poi.get('desc'): st.caption(poi['desc'][:70] + "..." if len(poi['desc']) > 70 else poi['desc'])

        with col_action:
            st.write("")
            if st.button("🗑️", key=f"del_sty_{poi['id']}", help="Remover"):
                st.session_state['cities'][city_id]['pois'] = [p for p in st.session_state['cities'][city_id]['pois'] if p['id'] != poi['id']]
                save_data(); st.rerun()

def render_city_planner(city_id):
    if city_id not in st.session_state['cities']:
        st.session_state['selected_city_id'] = None; st.rerun(); return

    city = st.session_state['cities'][city_id]
    
    # --- INICIALIZAÇÃO DE ESTADO ---
    if 'new_poi_name' not in st.session_state: st.session_state['new_poi_name'] = ""
    if 'new_poi_lat' not in st.session_state: st.session_state['new_poi_lat'] = str(city['lat'])
    if 'new_poi_lon' not in st.session_state: st.session_state['new_poi_lon'] = str(city['lon'])

    c1, c2 = st.columns([1, 6])
    if c1.button("⬅ Voltar"):
        st.session_state['selected_city_id'] = None; st.rerun()
    c2.title(city['name'])

    col_map, col_data = st.columns([1.5, 1])

    with col_map:
        DAY_COLORS = ['green', 'purple', 'orange', 'red', 'darkblue', 'cadetblue', 'darkred']
        
        m = folium.Map([city['lat'], city['lon']], zoom_start=13)
        
        for p in city['pois']:
            color = 'black' if p.get('type') == 'hotel' else (DAY_COLORS[(p.get('day', 0) - 1) % len(DAY_COLORS)] if p.get('day', 0) > 0 else 'blue')
            folium.Marker([p['lat'], p['lon']], popup=p['name'], icon=folium.Icon(color=color, icon='home' if p.get('type')=='hotel' else 'info-sign')).add_to(m)
        
        # Rotas
        visit_pois = [p for p in city['pois'] if p.get('day', 0) > 0]
        days = sorted(list(set(p['day'] for p in visit_pois)))
        hotel = next((p for p in city['pois'] if p.get('type')=='hotel'), None)
        for d in days:
            pts = [p for p in visit_pois if p['day'] == d]
            coords = []
            if hotel: coords.append([hotel['lat'], hotel['lon']])
            coords.extend([[p['lat'], p['lon']] for p in pts])
            if len(coords) > 1:
                line_color = DAY_COLORS[(d - 1) % len(DAY_COLORS)]
                folium.PolyLine(coords, color=line_color, weight=5, opacity=0.8, tooltip=f"Rota Dia {d}").add_to(m)
            
        map_data = st_folium(m, height=500, use_container_width=True)
        
        # --- LÓGICA DE INTERAÇÃO CRÍTICA ---
        clicked_poi = None
        
        if map_data:
            # 1. Detetar clique em objeto existente (Prioridade: APAGAR)
            if map_data.get('last_object_clicked'):
                lat_click = map_data['last_object_clicked']['lat']
                lon_click = map_data['last_object_clicked']['lng']
                for p in city['pois']:
                    if math.isclose(p['lat'], lat_click, abs_tol=0.0001) and math.isclose(p['lon'], lon_click, abs_tol=0.0001):
                        clicked_poi = p
                        break

            # 2. Detetar clique no vazio (Prioridade: PREENCHER INPUTS)
            if map_data.get("last_clicked") and not clicked_poi:
                new_lat = str(map_data["last_clicked"]["lat"])
                new_lon = str(map_data["last_clicked"]["lng"])
                
                if new_lat != st.session_state['new_poi_lat'] or new_lon != st.session_state['new_poi_lon']:
                    st.session_state['new_poi_lat'] = new_lat
                    st.session_state['new_poi_lon'] = new_lon
                    st.rerun()

        # --- PAINEL DE APAGAR (SE CLICOU EM PINO) ---
        if clicked_poi:
            with st.container(border=True):
                st.info(f"📍 Selecionado no Mapa: **{clicked_poi['name']}**")
                if st.button("🗑️ Eliminar este local do mapa", key=f"del_map_{clicked_poi['id']}", type="primary", use_container_width=True):
                      st.session_state['cities'][city_id]['pois'] = [p for p in st.session_state['cities'][city_id]['pois'] if p['id'] != clicked_poi['id']]
                      save_data()
                      st.toast(f"Local '{clicked_poi['name']}' removido!")
                      st.rerun()

    with col_data:
        tabs = st.tabs(["📝 Novo Local", "📅 Roteiro", "⚙️ Otimizar"])
        
        with tabs[0]:
            st.markdown("##### 🔍 Pesquisa & Adição")
            c_search, c_btn = st.columns([3, 1])
            search_query = c_search.text_input("Pesquisar Local", label_visibility="collapsed", placeholder="Ex: Torre Eiffel ou Av. Liberdade, Lisboa")
            
            if c_btn.button("🔍"):
                if search_query:
                    with st.spinner("A pesquisar..."):
                        s_lat, s_lon, s_addr = search_place_nominatim(search_query)
                        if s_lat:
                            st.session_state['new_poi_name'] = search_query
                            st.session_state['new_poi_lat'] = str(s_lat)
                            st.session_state['new_poi_lon'] = str(s_lon)
                            st.success(f"Encontrado: {s_addr[:40]}...")
                            st.rerun()
                        else: st.error("Não encontrado.")

            st.markdown("---")
            is_hotel = st.checkbox("É o Hotel/Base?")
            name = st.text_input("Nome", key="new_poi_name")
            
            # --- NOVA FEATURE: ADICIONAR POR ENDEREÇO MANUAL ---
            st.markdown("###### Morada / Endereço (Opcional)")
            c_addr_in, c_addr_btn = st.columns([3, 1])
            addr_manual = c_addr_in.text_input("address_manual", label_visibility="collapsed", placeholder="Digite a morada para buscar coords...")
            if c_addr_btn.button("📍 Buscar", help="Obter coordenadas desta morada"):
                if addr_manual:
                    a_lat, a_lon, a_full = search_place_nominatim(addr_manual)
                    if a_lat:
                        st.session_state['new_poi_lat'] = str(a_lat)
                        st.session_state['new_poi_lon'] = str(a_lon)
                        if not st.session_state['new_poi_name']:
                            st.session_state['new_poi_name'] = addr_manual
                        st.success("Coordenadas Preenchidas!")
                        st.rerun()
                    else:
                        st.error("Morada inválida.")
            # ----------------------------------------------------

            # Inputs vinculados ao Session State
            c_lat, c_lon = st.columns(2)
            raw_lat_poi = c_lat.text_input("Lat", key="new_poi_lat")
            raw_lon_poi = c_lon.text_input("Lon", key="new_poi_lon")
            
            time = st.number_input("Duração (min)", value=0 if is_hotel else 60)
            cost = st.number_input("Custo (€)", value=0.0)
            
            if st.button("💾 Salvar Local no Mapa", type="primary", use_container_width=True):
                lat_final = parse_coordinate(raw_lat_poi)
                lon_final = parse_coordinate(raw_lon_poi)
                
                # Se lat/lon vazios, tenta usar a morada manual se existir
                if (lat_final is None or lon_final is None) and addr_manual:
                     l, lo, _ = search_place_nominatim(addr_manual)
                     if l: lat_final, lon_final = l, lo

                if lat_final is not None and lon_final is not None:
                    if is_hotel:
                        for p in city['pois']: 
                            if p.get('type')=='hotel': p['type']='visit'
                    city['pois'].append({"id":str(uuid.uuid4()), "name":name if name else (addr_manual if addr_manual else "Sem Nome"), "lat":lat_final, "lon":lon_final, "time_min":time, "cost":cost, "type":'hotel' if is_hotel else 'visit', "day":0})
                    save_data(); st.success("Adicionado!"); st.rerun()
                else: st.error("Coordenadas inválidas e morada não encontrada.")

        with tabs[1]:
            st.markdown("""<style>.stExpander { border: none !important; box-shadow: none !important; } .element-container { margin-bottom: 0.5rem; }</style>""", unsafe_allow_html=True)
            visitas = [p for p in city['pois'] if p.get('type')!='hotel']
            days = sorted(list(set(p.get('day',0) for p in visitas)))
            hotel = next((p for p in city['pois'] if p.get('type') == 'hotel'), None)
            
            if hotel:
                with st.container(border=True):
                    c_h1, c_h2 = st.columns([1, 5])
                    with c_h1: st.markdown("<div style='font-size: 2em; text-align:center;'>🏨</div>", unsafe_allow_html=True)
                    with c_h2: 
                        st.markdown(f"**Base: {hotel['name']}**")
                        st.caption("Ponto de partida e chegada diário")

            if not days and not visitas: st.info("O roteiro está vazio.")
            
            for d in days:
                if d == 0:
                    st.markdown("---")
                    with st.expander(f"📌 **Itens Não Agendados ({len([x for x in visitas if x.get('day')==0])})**", expanded=False):
                        for p in [x for x in visitas if x.get('day')==0]: render_stylish_card(p, city_id, is_first=True)
                else:
                    st.markdown("<br>", unsafe_allow_html=True)
                    p_dia = [x for x in visitas if x['day']==d]
                    total_min = sum(p['time_min'] for p in p_dia)
                    st.markdown(f"""<div style="background-color: #f0f8ff; padding: 15px; border-radius: 10px; border-left: 5px solid #007bff; margin-bottom: 20px;">
                            <h4 style="margin:0; color: #004085;">🗓️ Dia {d}</h4>
                            <span style="font-size: 0.9em; color: #555;">{len(p_dia)} Locais • Aprox. {total_min//60}h {total_min%60}m de visita</span>
                        </div>""", unsafe_allow_html=True)
                    
                    for per_name, per_icon in [('Manhã', '🌅'), ('Tarde', '🌇')]:
                        p_per = [x for x in p_dia if x.get('period') == per_name]
                        if p_per:
                            st.markdown(f"##### {per_icon} {per_name}")
                            for idx, p in enumerate(p_per):
                                is_first_item = (idx == 0) and (per_name == 'Manhã' or not [x for x in p_dia if x.get('period') == 'Manhã'])
                                render_stylish_card(p, city_id, is_first=is_first_item)
                            st.markdown("<br>", unsafe_allow_html=True)

        with tabs[2]:
            st.write("#### AI Optimizer")
            st.caption(f"Simulated Annealing | Tolerância: {TOLERANCIA_MINUTOS}min")
            c1, c2 = st.columns(2)
            hm = c1.number_input("Horas Manhã", 1, 8, 4)
            ht = c2.number_input("Horas Tarde", 1, 8, 4)
            if st.button("🚀 Otimizar", use_container_width=True):
                with st.spinner("Otimizando rota..."):
                    res, msg = run_optimization_logic(city['pois'], hm, ht)
                    if res:
                        st.session_state['cities'][city_id]['pois'] = res
                        save_data(); st.success(msg); st.rerun()
                    else: st.error(msg)

# --- MAIN ---
if 'cities' not in st.session_state: st.session_state['cities'] = load_data()
if 'selected_city_id' not in st.session_state: st.session_state['selected_city_id'] = None

if st.session_state['selected_city_id']:
    render_city_planner(st.session_state['selected_city_id'])
else:
    render_dashboard()