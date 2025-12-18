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
DRIVING_SPEED_KMH = 35.0 
TOLERANCIA_MINUTOS = 30 

# Configuração Visual dos Tipos
TYPE_CONFIG = {
    'hotel': {'label': 'Hotel', 'color': 'black', 'icon': 'home', 'fa': 'fa-home'},
    'visit': {'label': 'Visita (Padrão)', 'color': 'blue', 'icon': 'camera', 'fa': 'fa-camera'},
    'food': {'label': 'Restaurante', 'color': 'red', 'icon': 'cutlery', 'fa': 'fa-cutlery'},
    'transport': {'label': 'Transporte', 'color': 'gray', 'icon': 'plane', 'fa': 'fa-plane'}
}

# --- FUNÇÕES UTILITÁRIAS ---

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
                dist = geodesic((p1['lat'], p1['lon']), (p2['lat'], p2['lon'])).km
                
                if p1.get('type') == 'hotel': speed = DRIVING_SPEED_KMH
                else: speed = WALKING_SPEED_KMH
                
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
    visit_pois = [p for p in pois if p.get('type') == 'visit']
    
    if not hotel: return None, "Defina um Hotel/Base."
    if not visit_pois: return pois, "Adicione locais do tipo 'Visita' para gerar roteiro."
    
    optimizer = TravelOptimizer(visit_pois, hotel, max_h_manha, max_h_tarde)
    optimized_schedule = optimizer.solve_simulated_annealing()
    msg = "Otimização concluída!"

    optimized_ids = set(p['id'] for p in optimized_schedule)
    others = [p for p in pois if p['id'] not in optimized_ids]
    for o in others:
        o['day'] = 0
        o['period'] = '-'
    
    return optimized_schedule + others, msg

# --- UI COMPONENTS ---

def render_sidebar_login():
    """Gerencia a autenticação na barra lateral."""
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    with st.sidebar:
        st.header("🔒 Acesso Admin")
        
        if not st.session_state['authenticated']:
            password = st.text_input("Senha de Admin", type="password")
            if st.button("Entrar"):
                if password == ADMIN_PASSWORD:
                    st.session_state['authenticated'] = True
                    st.success("Login efetuado!")
                    st.rerun()
                else:
                    st.error("Senha incorreta.")
            st.info("Modo: 👀 Apenas Leitura")
        else:
            st.success("✅ Autenticado (Modo Edição)")
            if st.button("Sair / Logout"):
                st.session_state['authenticated'] = False
                st.rerun()

def render_dashboard():
    st.title("🌍 AI Travel Planner")
    st.caption("Suporta pesquisa de locais (OSM) e coordenadas decimais.")
    st.markdown("---")

    # --- PROTEÇÃO: CRIAR CIDADE ---
    if st.session_state.get('authenticated'):
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
    else:
        st.info("🔒 Faça login na barra lateral para adicionar novos destinos.")

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
            
            # Ajuste de colunas dependendo da autenticação
            if st.session_state.get('authenticated'):
                col_plan, col_del = st.columns([4, 1])
            else:
                col_plan = st.container()

            with col_plan:
                if st.button(f"Planear", key=f"btn_plan_{cid}", use_container_width=True):
                    st.session_state['selected_city_id'] = cid
                    st.rerun()
            
            # --- PROTEÇÃO: APAGAR CIDADE ---
            if st.session_state.get('authenticated'):
                with col_del:
                    if st.button("🗑️", key=f"btn_del_{cid}", help="Apagar destino"):
                        del st.session_state['cities'][cid]
                        save_data(); st.toast("Removido!"); st.rerun()

def render_stylish_card(poi, city_id, is_first=False):
    """Renderiza um cartão. Se não autenticado, mostra apenas dados (sem dropdown/delete)."""
    
    is_auth = st.session_state.get('authenticated', False)

    # --- 1. Exibir tempo de deslocamento ---
    if not is_first and 'transit_prev' in poi and poi['transit_prev'] > 0 and poi.get('day', 0) > 0:
        icon_transit = "🚗" if poi.get('transit_prev') > 45 else "🚶"
        st.markdown(f"""
        <div style="text-align: center; color: #888; font-size: 0.8em; margin: 5px 0;">
            ⋮<br>{icon_transit} <i>{poi['transit_prev']} min deslocamento</i><br>⋮
        </div>
        """, unsafe_allow_html=True)

    with st.container(border=True):
        # Layout condicional
        if is_auth:
            col_icon, col_info, col_move, col_action = st.columns([0.8, 4, 2, 0.5])
        else:
            col_icon, col_info, col_move = st.columns([0.8, 4, 2])

        with col_icon:
            p_type = poi.get('type', 'visit')
            icon_char = "📍"
            if p_type == 'hotel': icon_char = "🏨"
            elif p_type == 'food': icon_char = "🍴"
            elif p_type == 'transport': icon_char = "✈️"
            st.markdown(f"<div style='font-size: 2.2em; text-align: center; padding-top: 5px;'>{icon_char}</div>", unsafe_allow_html=True)
        
        with col_info:
            st.markdown(f"**{poi['name']}**")
            tags = []
            type_label = TYPE_CONFIG.get(poi.get('type', 'visit'), {}).get('label', 'Local')
            tags.append(f"{type_label}")
            if poi.get('type') == 'visit': tags.append(f"⏱️ {poi['time_min']} min")
            if poi.get('cost', 0) > 0: tags.append(f"💶 {poi['cost']}€")
            
            if tags:
                tags_html = "".join([f"<span style='background-color: #f0f2f6; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; margin-right: 5px; color: #444; border: 1px solid #e0e0e0;'>{t}</span>" for t in tags])
                st.markdown(tags_html, unsafe_allow_html=True)
            if poi.get('desc'): st.caption(poi['desc'][:60] + "...")

        # --- PROTEÇÃO: MOVER E APAGAR ---
        with col_move:
            if poi.get('type') != 'hotel':
                current_val_str = "📌 Não Agendado"
                if poi.get('day', 0) > 0:
                    current_val_str = f"Dia {poi['day']} - {poi.get('period', 'Manhã')}"

                if is_auth:
                    # LÓGICA DE EDIÇÃO (DROPDOWN)
                    all_pois = st.session_state['cities'][city_id]['pois']
                    max_day = max([p.get('day', 0) for p in all_pois] + [0])
                    limit_day = max(max_day + 1, 3)
                    
                    move_options = {"📌 Não Agendado": (0, '-')}
                    ordered_keys = ["📌 Não Agendado"]
                    for d in range(1, limit_day + 1):
                        for per in ['Manhã', 'Tarde']:
                            key_str = f"Dia {d} - {per}"
                            ordered_keys.append(key_str)
                            move_options[key_str] = (d, per)
                    
                    if current_val_str not in ordered_keys:
                        ordered_keys.append(current_val_str)
                        move_options[current_val_str] = (poi['day'], poi.get('period', '-'))

                    selected_opt = st.selectbox("Mover", options=ordered_keys, index=ordered_keys.index(current_val_str), key=f"mv_{poi['id']}", label_visibility="collapsed")

                    if selected_opt != current_val_str:
                        new_day, new_period = move_options[selected_opt]
                        target_poi = next(p for p in st.session_state['cities'][city_id]['pois'] if p['id'] == poi['id'])
                        target_poi['day'] = new_day
                        target_poi['period'] = new_period
                        save_data(); st.rerun()
                else:
                    # LÓGICA APENAS LEITURA
                    st.markdown(f"<div style='margin-top: 5px; font-size: 0.9em; color: #666;'>{current_val_str}</div>", unsafe_allow_html=True)
            else:
                st.caption("Base Fixa")

        if is_auth:
            with col_action:
                st.write("")
                if st.button("🗑️", key=f"del_sty_{poi['id']}", help="Remover"):
                    st.session_state['cities'][city_id]['pois'] = [p for p in st.session_state['cities'][city_id]['pois'] if p['id'] != poi['id']]
                    save_data(); st.rerun()

def render_city_planner(city_id):
    if city_id not in st.session_state['cities']:
        st.session_state['selected_city_id'] = None; st.rerun(); return

    city = st.session_state['cities'][city_id]
    is_auth = st.session_state.get('authenticated', False)
    
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
            p_type = p.get('type', 'visit')
            day = p.get('day', 0)
            color = TYPE_CONFIG.get(p_type, {}).get('color', 'blue')
            icon_name = TYPE_CONFIG.get(p_type, {}).get('icon', 'info-sign')
            if p_type == 'visit' and day > 0: color = DAY_COLORS[(day - 1) % len(DAY_COLORS)]
            folium.Marker([p['lat'], p['lon']], popup=f"{p['name']}", icon=folium.Icon(color=color, icon=icon_name, prefix='fa')).add_to(m)
        
        visit_pois = [p for p in city['pois'] if p.get('day', 0) > 0 and p.get('type') == 'visit']
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
        
        # --- PROTEÇÃO: CLIQUE NO MAPA ---
        clicked_poi = None
        if is_auth and map_data:
            if map_data.get('last_object_clicked'):
                lat_click = map_data['last_object_clicked']['lat']
                lon_click = map_data['last_object_clicked']['lng']
                for p in city['pois']:
                    if math.isclose(p['lat'], lat_click, abs_tol=0.0001) and math.isclose(p['lon'], lon_click, abs_tol=0.0001):
                        clicked_poi = p; break

            if map_data.get("last_clicked") and not clicked_poi:
                new_lat = str(map_data["last_clicked"]["lat"])
                new_lon = str(map_data["last_clicked"]["lng"])
                if new_lat != st.session_state['new_poi_lat'] or new_lon != st.session_state['new_poi_lon']:
                    st.session_state['new_poi_lat'] = new_lat
                    st.session_state['new_poi_lon'] = new_lon
                    st.rerun()

        if clicked_poi and is_auth:
            with st.container(border=True):
                st.info(f"📍 Selecionado: **{clicked_poi['name']}**")
                if st.button("🗑️ Eliminar do mapa", key=f"del_map_{clicked_poi['id']}", type="primary"):
                      st.session_state['cities'][city_id]['pois'] = [p for p in st.session_state['cities'][city_id]['pois'] if p['id'] != clicked_poi['id']]
                      save_data(); st.rerun()

    with col_data:
        tabs = st.tabs(["📝 Novo Local", "📅 Roteiro", "⚙️ Otimizar"])
        
        # --- ABA 1: NOVO LOCAL (Protegida) ---
        with tabs[0]:
            if is_auth:
                st.markdown("##### 🔍 Pesquisa & Adição")
                c_search, c_btn = st.columns([3, 1])
                search_query = c_search.text_input("Pesquisar Local", label_visibility="collapsed")
                if c_btn.button("🔍") and search_query:
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
                
                type_options = list(TYPE_CONFIG.keys())
                label_to_key = {v['label']: k for k, v in TYPE_CONFIG.items()}
                selected_label = st.selectbox("Tipo", list(label_to_key.keys()), index=1)
                selected_type = label_to_key[selected_label]
                
                name = st.text_input("Nome", key="new_poi_name")
                
                # Manual Address
                c_addr_in, c_addr_btn = st.columns([3, 1])
                addr_manual = c_addr_in.text_input("address_manual", label_visibility="collapsed", placeholder="Morada Manual...")
                if c_addr_btn.button("📍", help="Buscar coords"):
                    if addr_manual:
                        a_lat, a_lon, _ = search_place_nominatim(addr_manual)
                        if a_lat:
                            st.session_state['new_poi_lat'] = str(a_lat)
                            st.session_state['new_poi_lon'] = str(a_lon)
                            if not name: st.session_state['new_poi_name'] = addr_manual
                            st.rerun()

                c_lat, c_lon = st.columns(2)
                raw_lat_poi = c_lat.text_input("Lat", key="new_poi_lat")
                raw_lon_poi = c_lon.text_input("Lon", key="new_poi_lon")
                
                time_val = 60
                if selected_type == 'visit': time_val = st.number_input("Duração (min)", value=60)
                cost = st.number_input("Custo (€)", value=0.0)
                
                if st.button("💾 Salvar Local", type="primary", use_container_width=True):
                    lat_final = parse_coordinate(raw_lat_poi)
                    lon_final = parse_coordinate(raw_lon_poi)
                    
                    if (lat_final is None or lon_final is None) and addr_manual:
                         l, lo, _ = search_place_nominatim(addr_manual)
                         if l: lat_final, lon_final = l, lo

                    if lat_final is not None and lon_final is not None:
                        if selected_type == 'hotel':
                            for p in city['pois']: 
                                if p.get('type')=='hotel': p['type']='visit'
                        
                        city['pois'].append({
                            "id":str(uuid.uuid4()), "name":name if name else (addr_manual if addr_manual else "Sem Nome"), 
                            "lat":lat_final, "lon":lon_final, "time_min":time_val, 
                            "cost":cost, "type":selected_type, "day":0
                        })
                        save_data(); st.success("Adicionado!"); st.rerun()
                    else: st.error("Coordenadas inválidas.")

                st.markdown("---")
                with st.expander("📂 Importar .txt", expanded=False):
                    uploaded_file = st.file_uploader("Arquivo", type=['txt'], label_visibility="collapsed")
                    if uploaded_file and st.button("📥 Processar"):
                        try:
                            stringio = uploaded_file.getvalue().decode("utf-8")
                            count = 0
                            for line in stringio.splitlines():
                                if not line.strip(): continue
                                parts = line.split(',')
                                if len(parts) >= 3:
                                    t_lat = parse_coordinate(parts[1])
                                    t_lon = parse_coordinate(parts[2])
                                    if t_lat and t_lon:
                                        city['pois'].append({
                                            "id": str(uuid.uuid4()), "name": parts[0].strip(),
                                            "lat": t_lat, "lon": t_lon, "time_min": 60, "cost": 0, "type": 'visit', "day": 0
                                        })
                                        count += 1
                            save_data(); st.success(f"{count} importados!"); st.rerun()
                        except Exception as e: st.error(str(e))
                
                st.markdown("---")
                if st.button("🗑️ Remover TODOS os locais", type="primary"):
                    city['pois'] = []; save_data(); st.rerun()
            else:
                st.warning("🔒 Modo Leitura. Faça login para editar.")

        # --- ABA 2: ROTEIRO ---
        with tabs[1]:
            st.markdown("""<style>.stExpander { border: none !important; box-shadow: none !important; } .element-container { margin-bottom: 0.5rem; }</style>""", unsafe_allow_html=True)
            visitas = [p for p in city['pois'] if p.get('type')!='hotel']
            days = sorted(list(set(p.get('day',0) for p in city['pois'] if p.get('day', 0) > 0)))
            hotel = next((p for p in city['pois'] if p.get('type') == 'hotel'), None)
            
            if hotel:
                with st.container(border=True):
                    c_h1, c_h2 = st.columns([1, 5])
                    with c_h1: st.markdown("<div style='font-size: 2em; text-align:center;'>🏨</div>", unsafe_allow_html=True)
                    with c_h2: st.markdown(f"**Base: {hotel['name']}**"); st.caption("Ponto de partida")

            if not days and not visitas: st.info("O roteiro está vazio.")
            
            for d in days:
                st.markdown("<br>", unsafe_allow_html=True)
                p_dia = [x for x in visitas if x.get('day')==d]
                total_min = sum(p.get('time_min',0) for p in p_dia)
                st.markdown(f"""<div style="background-color: #f0f8ff; padding: 15px; border-radius: 10px; border-left: 5px solid #007bff; margin-bottom: 20px;">
                        <h4 style="margin:0; color: #004085;">🗓️ Dia {d}</h4>
                        <span style="font-size: 0.9em; color: #555;">{len(p_dia)} Locais • {total_min//60}h {total_min%60}m</span>
                    </div>""", unsafe_allow_html=True)
                
                for per_name, per_icon in [('Manhã', '🌅'), ('Tarde', '🌇')]:
                    p_per = [x for x in p_dia if x.get('period') == per_name]
                    if p_per:
                        st.markdown(f"##### {per_icon} {per_name}")
                        for idx, p in enumerate(p_per):
                            is_first_item = (idx == 0) and (per_name == 'Manhã' or not [x for x in p_dia if x.get('period') == 'Manhã'])
                            render_stylish_card(p, city_id, is_first=is_first_item)
                        st.markdown("<br>", unsafe_allow_html=True)

            unscheduled = [x for x in city['pois'] if x.get('day', 0) == 0 and x.get('type') != 'hotel']
            if unscheduled:
                st.markdown("---")
                with st.expander(f"📌 **Itens Não Agendados ({len(unscheduled)})**", expanded=True):
                    for tipo_code in ['visit', 'food', 'transport']:
                        grupo = [x for x in unscheduled if x.get('type') == tipo_code]
                        if grupo:
                            st.caption(f"**{TYPE_CONFIG[tipo_code]['label']}**")
                            for p in grupo: render_stylish_card(p, city_id, is_first=True)

        # --- ABA 3: OTIMIZAR (Protegida) ---
        with tabs[2]:
            if is_auth:
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
            else:
                st.warning("🔒 Login necessário para otimização automática.")

# --- MAIN ---
if 'cities' not in st.session_state: st.session_state['cities'] = load_data()
if 'selected_city_id' not in st.session_state: st.session_state['selected_city_id'] = None

render_sidebar_login()

if st.session_state['selected_city_id']:
    render_city_planner(st.session_state['selected_city_id'])
else:
    render_dashboard()
